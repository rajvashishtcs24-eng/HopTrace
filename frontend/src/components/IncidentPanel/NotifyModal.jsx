import { useState, useEffect, useCallback } from 'react';
import { useApi } from '../../hooks/useApi';
import useStore from '../../store/appStore';

export default function NotifyModal({ isOpen, onClose, incident, initialKind = 'outage' }) {
  const { fetchNotificationPreview, fetchNotificationDeliveries, notifyIncident } = useApi();
  const addToast = useStore(s => s.addToast);

  const [step, setStep] = useState('preview'); // 'preview' | 'confirm' | 'results'
  const [messageKind, setMessageKind] = useState(initialKind); // 'outage' | 'restoration'
  const [channel, setChannel] = useState('sms');

  const [loadingPreview, setLoadingPreview] = useState(false);
  const [previewData, setPreviewData] = useState(null);
  const [previewError, setPreviewError] = useState(null);

  const [dispatching, setDispatching] = useState(false);
  const [dispatchResult, setDispatchResult] = useState(null);
  const [dispatchError, setDispatchError] = useState(null);

  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyData, setHistoryData] = useState(null);

  // Sync initial kind if opened for restoration
  useEffect(() => {
    if (isOpen) {
      setMessageKind(initialKind);
      setStep('preview');
      setDispatchResult(null);
      setDispatchError(null);
    }
  }, [isOpen, initialKind]);

  // Load preview data whenever modal opens, or kind/channel changes
  const loadPreview = useCallback(async () => {
    if (!incident?.id) return;
    setLoadingPreview(true);
    setPreviewError(null);
    try {
      const data = await fetchNotificationPreview(incident.id, { channel, messageKind });
      setPreviewData(data);
    } catch (err) {
      setPreviewError(err?.message || 'Failed to generate notification previews');
    } finally {
      setLoadingPreview(false);
    }
  }, [incident?.id, channel, messageKind, fetchNotificationPreview]);

  // Load persisted delivery history
  const loadHistory = useCallback(async () => {
    if (!incident?.id) return;
    setHistoryLoading(true);
    try {
      const res = await fetchNotificationDeliveries(incident.id, messageKind);
      setHistoryData(res);
    } catch (err) {
      console.warn('Failed to load notification history:', err);
    } finally {
      setHistoryLoading(false);
    }
  }, [incident?.id, messageKind, fetchNotificationDeliveries]);

  useEffect(() => {
    if (isOpen) {
      loadPreview();
      loadHistory();
    }
  }, [isOpen, loadPreview, loadHistory]);

  if (!isOpen || !incident) return null;

  const providerName = previewData?.provider || 'unavailable';
  const isProviderAvailable = Boolean(previewData?.provider_available);
  const previews = previewData?.previews || [];
  const essentialCount = previews.filter(p => p.is_essential).length;
  const validCount = previews.filter(p => p.phone_valid).length;

  const handleSend = async () => {
    setDispatching(true);
    setDispatchError(null);
    try {
      const res = await notifyIncident(incident.id, {
        channel,
        messageKind,
      });
      setDispatchResult(res);
      setStep('results');
      loadHistory();
      addToast(
        `Dispatched ${messageKind} alerts: ${res.sent_count} sent, ${res.skipped_count || 0} skipped`,
        'success'
      );
    } catch (err) {
      const msg = err?.message || 'Dispatch failed';
      setDispatchError(msg);
      if (msg.includes('503')) {
        addToast('Notification provider is unavailable or unconfigured (503)', 'error');
      } else {
        addToast(`Notification error: ${msg}`, 'error');
      }
    } finally {
      setDispatching(false);
    }
  };

  const handleRetry = async () => {
    await handleSend();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-fade-in">
      <div className="bg-[#0b1728] border border-slate-700/80 rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden">
        
        {/* Header */}
        <div className="px-6 py-4 bg-slate-900/90 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-xl">📢</span>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-white">
                  {messageKind === 'restoration' ? 'Notify Service Restoration' : 'Notify Affected Subscribers'}
                </h2>
                <span className="text-xs px-2 py-0.5 rounded font-mono font-semibold bg-slate-800 border border-slate-700 text-amber-300">
                  {incident.id}
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Reconciled blast radius dispatch with deterministic multilingual templates
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Kind Switcher Tabs */}
            <div className="flex bg-slate-950 p-1 rounded-lg border border-slate-800 text-xs">
              <button
                type="button"
                onClick={() => { setMessageKind('outage'); setStep('preview'); }}
                className={`px-3 py-1 rounded-md font-semibold transition-all ${
                  messageKind === 'outage'
                    ? 'bg-amber-500 text-slate-950 shadow-sm'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                Outage (बाधा)
              </button>
              <button
                type="button"
                onClick={() => { setMessageKind('restoration'); setStep('preview'); }}
                className={`px-3 py-1 rounded-md font-semibold transition-all ${
                  messageKind === 'restoration'
                    ? 'bg-emerald-500 text-slate-950 shadow-sm'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                Restoration (बहाली)
              </button>
            </div>

            <button
              onClick={onClose}
              className="text-slate-400 hover:text-white text-lg p-1 hover:bg-slate-800 rounded-lg transition-colors"
              title="Close modal"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Step Indicator */}
        <div className="px-6 py-2.5 bg-slate-950/60 border-b border-slate-800/80 flex items-center justify-between text-xs">
          <div className="flex items-center gap-4">
            <span className={`flex items-center gap-1.5 font-semibold ${step === 'preview' ? 'text-amber-400' : 'text-slate-500'}`}>
              <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[11px] ${step === 'preview' ? 'bg-amber-500 text-slate-950 font-bold' : 'bg-slate-800 text-slate-400'}`}>1</span>
              Audience & Message Preview
            </span>
            <span className="text-slate-600">→</span>
            <span className={`flex items-center gap-1.5 font-semibold ${step === 'confirm' ? 'text-amber-400' : 'text-slate-500'}`}>
              <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[11px] ${step === 'confirm' ? 'bg-amber-500 text-slate-950 font-bold' : 'bg-slate-800 text-slate-400'}`}>2</span>
              Provider Confirmation
            </span>
            <span className="text-slate-600">→</span>
            <span className={`flex items-center gap-1.5 font-semibold ${step === 'results' ? 'text-emerald-400' : 'text-slate-500'}`}>
              <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[11px] ${step === 'results' ? 'bg-emerald-500 text-slate-950 font-bold' : 'bg-slate-800 text-slate-400'}`}>3</span>
              Delivery Audit Table
            </span>
          </div>

          {/* Quick history switch */}
          {historyData && historyData.total_count > 0 && (
            <button
              onClick={() => setStep('results')}
              className="text-slate-400 hover:text-amber-300 flex items-center gap-1 text-[11px] underline underline-offset-2"
            >
              <span>View Past Dispatches ({historyData.total_count})</span>
            </button>
          )}
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          
          {/* STEP 1: PREVIEW */}
          {step === 'preview' && (
            <div className="space-y-4">
              {/* Provider Info Banner */}
              <div className={`p-3.5 rounded-xl border flex items-start gap-3 ${
                !isProviderAvailable
                  ? 'bg-rose-950/40 border-rose-800/80 text-rose-200'
                  : providerName === 'console'
                  ? 'bg-amber-950/30 border-amber-700/60 text-amber-200'
                  : 'bg-emerald-950/30 border-emerald-700/60 text-emerald-200'
              }`}>
                <span className="text-lg mt-0.5">
                  {!isProviderAvailable ? '⚠️' : providerName === 'console' ? '💻' : '📱'}
                </span>
                <div className="flex-1 text-xs space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-sm">
                      Provider: <span className="uppercase">{providerName}</span>
                    </span>
                    <span className={`px-2 py-0.5 rounded font-mono font-bold text-[10px] uppercase border ${
                      !isProviderAvailable
                        ? 'bg-rose-900/60 border-rose-600 text-rose-300'
                        : 'bg-emerald-900/60 border-emerald-500 text-emerald-300'
                    }`}>
                      {isProviderAvailable ? 'Ready' : 'Unconfigured (503)'}
                    </span>
                  </div>
                  <p className="text-slate-300">
                    {!isProviderAvailable
                      ? 'Outage notification provider is not configured on the server. Previews render normally, but sending will return HTTP 503. To enable real or simulated dispatch, set NOTIFICATION_PROVIDER=console or twilio.'
                      : providerName === 'console'
                      ? 'Console Mode Active: All dispatches will be recorded in SQLite and marked as "simulated (not delivered)". No real cellular SMS charges.'
                      : 'Twilio Cellular Active: Live cellular SMS will be dispatched via Twilio to authorized numbers (allowlist enforced for live incidents).'}
                  </p>
                </div>
              </div>

              {/* Priority Audience Breakdown */}
              <div className="grid grid-cols-3 gap-3">
                <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3">
                  <div className="text-xs text-slate-400 font-medium">Total Targeted</div>
                  <div className="text-xl font-bold text-white mt-1">{previews.length}</div>
                  <div className="text-[11px] text-slate-500 mt-0.5">
                    {messageKind === 'restoration' ? 'Filtered to outage recipients' : 'Reconciled blast radius'}
                  </div>
                </div>

                <div className="bg-slate-900/60 border border-emerald-900/40 rounded-xl p-3">
                  <div className="text-xs text-emerald-400 font-semibold flex items-center gap-1">
                    <span>🏥</span>
                    <span>Essential Public Services</span>
                  </div>
                  <div className="text-xl font-bold text-emerald-300 mt-1">{essentialCount}</div>
                  <div className="text-[11px] text-emerald-500/80 mt-0.5">Health centres, schools, panchayat</div>
                </div>

                <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3">
                  <div className="text-xs text-slate-400 font-medium">Valid E.164 Phones</div>
                  <div className="text-xl font-bold text-white mt-1">
                    {validCount} <span className="text-xs font-normal text-slate-500">/ {previews.length}</span>
                  </div>
                  <div className="text-[11px] text-slate-500 mt-0.5">
                    {previews.length - validCount > 0 ? `${previews.length - validCount} invalid numbers skipped` : '100% E.164 compliant'}
                  </div>
                </div>
              </div>

              {/* Recipient Preview List */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs text-slate-400 font-semibold uppercase">
                  <span>Recipient Preview Queue (Essential Services First)</span>
                  <span>Deterministic multilingual template</span>
                </div>

                {loadingPreview ? (
                  <div className="py-12 flex flex-col items-center justify-center gap-2 text-slate-400">
                    <span className="w-6 h-6 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
                    <span className="text-xs">Generating localized subscriber previews…</span>
                  </div>
                ) : previews.length === 0 ? (
                  <div className="py-12 text-center text-slate-500 text-xs border border-dashed border-slate-800 rounded-xl">
                    {messageKind === 'restoration'
                      ? 'No subscribers were sent an outage alert for this incident yet. Restoration notices default to outage recipients.'
                      : 'No affected subscribers found for this incident.'}
                  </div>
                ) : (
                  <div className="space-y-2.5 max-h-96 overflow-y-auto pr-1">
                    {previews.map((item) => (
                      <div
                        key={item.subscriber_id}
                        className={`p-3 rounded-xl border transition-all ${
                          item.is_essential
                            ? 'bg-slate-900/90 border-emerald-800/60'
                            : 'bg-slate-900/50 border-slate-800'
                        }`}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="space-y-1">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-sm font-bold text-white flex items-center gap-1.5">
                                {item.is_essential && <span title="Essential Public Service">🏥</span>}
                                {item.subscriber_name}
                              </span>
                              <span className="text-xs font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
                                {item.subscriber_id}
                              </span>
                              {item.is_essential && (
                                <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded bg-emerald-950 border border-emerald-600 text-emerald-300">
                                  Essential
                                </span>
                              )}
                              <span className="text-xs text-slate-400 font-medium capitalize">
                                📍 {item.village || 'Unknown Village'}
                              </span>
                            </div>

                            <div className="flex items-center gap-2 text-xs">
                              <span className="font-mono text-slate-300 bg-black/40 px-2 py-0.5 rounded border border-slate-800">
                                {item.phone}
                              </span>
                              <span
                                className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border ${
                                  item.phone_valid
                                    ? 'bg-emerald-950/60 border-emerald-700 text-emerald-300'
                                    : 'bg-rose-950/60 border-rose-700 text-rose-300'
                                }`}
                              >
                                {item.phone_valid ? '✓ E.164' : `⚠ ${item.phone_validation_reason || 'Invalid Phone'}`}
                              </span>
                              <span className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-sky-950/70 border border-sky-700 text-sky-300">
                                {item.preferred_language.toUpperCase()}
                              </span>
                              <span className="text-[10px] font-mono text-slate-500">
                                Source: {item.translation_source}
                              </span>
                            </div>
                          </div>
                        </div>

                        {/* Rendered Message Preview Bubble */}
                        <div className="mt-2.5 p-2.5 bg-black/40 border border-slate-800 rounded-lg text-xs text-slate-200 font-sans leading-relaxed">
                          <span className="text-amber-400 font-semibold mr-1.5">SMS Preview:</span>
                          {item.message}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* STEP 2: CONFIRMATION */}
          {step === 'confirm' && (
            <div className="space-y-4 max-w-2xl mx-auto py-2">
              <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 space-y-4">
                <div className="flex items-center gap-2 text-amber-400 font-bold text-sm">
                  <span>⚠️</span>
                  <span>Confirm Dispatch Parameters</span>
                </div>

                <div className="p-4 bg-black/40 border border-slate-800 rounded-xl space-y-2 text-xs text-slate-300">
                  <p className="text-sm text-white font-medium">
                    You are about to dispatch an <strong className="text-amber-400 capitalize">{messageKind} Alert</strong> to{' '}
                    <strong className="text-white">{validCount} valid subscriber(s)</strong>.
                  </p>
                  <p>
                    Priority is given to <strong className="text-emerald-400">{essentialCount} essential public services</strong> (health clinics, schools, local governance).
                  </p>
                </div>

                {/* Plain-Words Provider Explainer */}
                <div className="p-4 rounded-xl border border-slate-700 bg-slate-950/80 space-y-2 text-xs">
                  <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                    <span className="text-slate-400 font-semibold uppercase text-[11px]">Active Provider</span>
                    <span className="font-bold text-white font-mono uppercase bg-slate-800 px-2 py-0.5 rounded">
                      {providerName}
                    </span>
                  </div>

                  {providerName === 'console' && (
                    <div className="text-amber-200/90 space-y-1">
                      <div className="font-semibold text-amber-300">Demo Simulation Mode</div>
                      <p className="text-slate-300 text-[11px] leading-relaxed">
                        This environment uses the <strong>Console Provider</strong>. Messages will be claimed atomically in SQLite and recorded as <strong>"simulated (not delivered)"</strong>. No actual cellular SMS messages will be billed or transmitted to physical handsets.
                      </p>
                    </div>
                  )}

                  {providerName === 'twilio' && (
                    <div className="text-emerald-200/90 space-y-1">
                      <div className="font-semibold text-emerald-300">Real Cellular Carrier Dispatch</div>
                      <p className="text-slate-300 text-[11px] leading-relaxed">
                        Messages will be dispatched over the cellular network via <strong>Twilio</strong>. For safety, real dispatches are restricted strictly to <strong>data_source = 'live'</strong> incidents and numbers configured in <code>NOTIFY_ALLOWLIST</code>.
                      </p>
                    </div>
                  )}
                </div>

                {/* Idempotency Safe Notice */}
                <div className="flex items-start gap-2.5 p-3 bg-sky-950/30 border border-sky-800/50 rounded-xl text-xs text-sky-200">
                  <span className="text-base">🔒</span>
                  <div>
                    <div className="font-bold text-sky-300">Atomic Idempotency Guarantee</div>
                    <div className="text-slate-300 text-[11px] mt-0.5">
                      Each subscriber is claimed atomically via SQLite <code>ON CONFLICT DO NOTHING</code>. Accidental double-clicks or repeated retries will never send duplicate alerts.
                    </div>
                  </div>
                </div>

                {dispatchError && (
                  <div className="p-3 bg-rose-950/50 border border-rose-800 rounded-xl text-xs text-rose-300">
                    <strong>Dispatch Error:</strong> {dispatchError}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* STEP 3: RESULTS & AUDIT TABLE */}
          {step === 'results' && (
            <div className="space-y-4">
              {/* Outcome Banner */}
              {dispatchResult && (
                <div className="p-4 bg-slate-900/90 border border-slate-800 rounded-2xl flex items-center justify-between">
                  <div className="space-y-0.5">
                    <div className="text-xs text-slate-400 font-semibold uppercase">Dispatch Complete</div>
                    <div className="text-sm font-bold text-white flex items-center gap-2">
                      <span>Provider: <span className="uppercase text-amber-400">{dispatchResult.provider}</span></span>
                      <span>·</span>
                      <span className="capitalize">{dispatchResult.message_kind} Alerts</span>
                    </div>
                  </div>

                  <div className="flex items-center gap-4 text-xs font-mono">
                    <div className="text-right">
                      <div className="text-slate-500">Targeted</div>
                      <div className="font-bold text-white text-base">{dispatchResult.total_targeted}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-emerald-400">Sent</div>
                      <div className="font-bold text-emerald-300 text-base">{dispatchResult.sent_count}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-amber-400">Skipped</div>
                      <div className="font-bold text-amber-300 text-base">{dispatchResult.skipped_count || 0}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-rose-400">Failed</div>
                      <div className="font-bold text-rose-300 text-base">{dispatchResult.failed_count}</div>
                    </div>
                  </div>
                </div>
              )}

              {/* Delivery History Table */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs text-slate-400 font-semibold uppercase">
                  <span>Persisted Delivery Audit History ({historyData?.total_count || 0} records)</span>
                  <button
                    onClick={loadHistory}
                    disabled={historyLoading}
                    className="text-amber-400 hover:text-amber-300 text-[11px] underline"
                  >
                    {historyLoading ? 'Refreshing…' : 'Refresh Table'}
                  </button>
                </div>

                {(!historyData || historyData.deliveries.length === 0) ? (
                  <div className="py-12 text-center text-slate-500 text-xs border border-dashed border-slate-800 rounded-xl">
                    No notification deliveries recorded yet for this incident.
                  </div>
                ) : (
                  <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-900/60">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead>
                        <tr className="bg-slate-950 text-slate-400 border-b border-slate-800 text-[11px] uppercase">
                          <th className="py-2.5 px-3 font-semibold">Subscriber</th>
                          <th className="py-2.5 px-3 font-semibold">Recipient</th>
                          <th className="py-2.5 px-3 font-semibold">Status</th>
                          <th className="py-2.5 px-3 font-semibold">Provider</th>
                          <th className="py-2.5 px-3 font-semibold">Message Delivered</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/80">
                        {historyData.deliveries.map((d, idx) => (
                          <tr key={idx} className="hover:bg-slate-800/40 transition-colors">
                            <td className="py-2 px-3 font-medium text-white">
                              {d.subscriber_id}
                            </td>
                            <td className="py-2 px-3 font-mono text-slate-300">
                              {d.recipient}
                            </td>
                            <td className="py-2 px-3">
                              <span
                                className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-bold uppercase border ${
                                  d.status === 'sent' && d.provider === 'console'
                                    ? 'bg-amber-950/60 border-amber-600/80 text-amber-300'
                                    : d.status === 'sent'
                                    ? 'bg-emerald-950/60 border-emerald-600/80 text-emerald-300'
                                    : d.status === 'failed'
                                    ? 'bg-rose-950/60 border-rose-600/80 text-rose-300'
                                    : 'bg-slate-800 border-slate-600 text-slate-400'
                                }`}
                              >
                                {d.delivery_status || d.status}
                              </span>
                              {d.error && (
                                <div className="text-[10px] text-rose-400 mt-0.5">{d.error}</div>
                              )}
                            </td>
                            <td className="py-2 px-3 uppercase font-mono text-slate-400 text-[11px]">
                              {d.provider}
                            </td>
                            <td className="py-2 px-3 text-slate-300 max-w-xs truncate text-[11px]" title={d.message}>
                              {d.message}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Modal Footer Controls */}
        <div className="px-6 py-3.5 bg-slate-900/90 border-t border-slate-800 flex items-center justify-between">
          <div>
            {step === 'confirm' && (
              <button
                type="button"
                onClick={() => setStep('preview')}
                disabled={dispatching}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg transition-colors"
              >
                ← Back to Review
              </button>
            )}
            {step === 'results' && (
              <button
                type="button"
                onClick={() => setStep('preview')}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg transition-colors"
              >
                ← Back to Previews
              </button>
            )}
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onClose}
              disabled={dispatching}
              className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-lg transition-colors"
            >
              {step === 'results' ? 'Close' : 'Cancel'}
            </button>

            {step === 'preview' && (
              <button
                type="button"
                onClick={() => setStep('confirm')}
                disabled={!isProviderAvailable || validCount === 0}
                className="px-5 py-2 bg-amber-500 hover:bg-amber-400 disabled:opacity-40 disabled:cursor-not-allowed text-slate-950 text-xs font-bold rounded-lg transition-all shadow-md flex items-center gap-1.5"
                title={!isProviderAvailable ? 'Notification provider is unconfigured (503)' : 'Continue to Confirmation'}
              >
                <span>Continue to Confirmation →</span>
              </button>
            )}

            {step === 'confirm' && (
              <button
                type="button"
                onClick={handleSend}
                disabled={dispatching}
                className="px-5 py-2 bg-amber-500 hover:bg-amber-400 disabled:opacity-50 text-slate-950 text-xs font-extrabold rounded-lg transition-all shadow-md flex items-center gap-2"
              >
                {dispatching ? (
                  <>
                    <span className="w-3.5 h-3.5 border-2 border-slate-950 border-t-transparent rounded-full animate-spin shrink-0" />
                    <span>Dispatched in progress…</span>
                  </>
                ) : (
                  <>
                    <span>🚀</span>
                    <span>Confirm & Dispatch ({validCount} Subscribers)</span>
                  </>
                )}
              </button>
            )}

            {step === 'results' && dispatchResult && (dispatchResult.failed_count > 0 || (dispatchResult.skipped_count || 0) > 0) && (
              <button
                type="button"
                onClick={handleRetry}
                disabled={dispatching}
                className="px-4 py-2 bg-amber-600 hover:bg-amber-500 text-white text-xs font-bold rounded-lg transition-colors"
              >
                {dispatching ? 'Retrying…' : 'Retry Failed / Skipped'}
              </button>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
