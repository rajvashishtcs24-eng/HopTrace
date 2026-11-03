import { useMemo, useState, useEffect, useRef } from 'react';
import { MapContainer, TileLayer, ScaleControl, useMap } from 'react-leaflet';
import useStore from '../../store/appStore';
import './leafletSetup';
import { computeBounds } from './geo';
import { telemetryLabel } from './theme';
import Legend from './Legend';

const ERROR_TILE_URL =
  'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';

/**
 * Resizes the Leaflet map whenever its DOM container dimensions change.
 */
function MapResizer() {
  const map = useMap();

  useEffect(() => {
    const container = map.getContainer();
    if (!container || typeof ResizeObserver === 'undefined') return;

    const observer = new ResizeObserver(() => {
      map.invalidateSize();
    });

    observer.observe(container);
    return () => {
      observer.disconnect();
    };
  }, [map]);

  return null;
}

/**
 * Fits the map view to the provided bounds once when coordinates become available,
 * without overriding manual pan/zoom on subsequent renders.
 */
function FitBoundsOnce({ bounds }) {
  const map = useMap();
  const hasFittedRef = useRef(false);

  useEffect(() => {
    if (bounds && !hasFittedRef.current) {
      hasFittedRef.current = true;
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 16 });
    }
  }, [bounds, map]);

  return null;
}

export default function VillageMap() {
  const topology = useStore((s) => s.topology);
  const bounds = useMemo(() => computeBounds(topology?.nodes), [topology?.nodes]);
  const dataSource = topology?.data_source ?? 'unknown';

  const [isOffline, setIsOffline] = useState(false);
  const tileLayerRef = useRef(null);

  useEffect(() => {
    const handleOffline = () => setIsOffline(true);
    const handleOnline = () => {
      setIsOffline(false);
      tileLayerRef.current?.redraw();
    };
    window.addEventListener('offline', handleOffline);
    window.addEventListener('online', handleOnline);
    return () => {
      window.removeEventListener('offline', handleOffline);
      window.removeEventListener('online', handleOnline);
    };
  }, []);

  if (dataSource === 'loading') {
    return (
      <div className="relative isolate w-full h-full min-h-[480px] bg-[#050d1a] flex flex-col items-center justify-center text-slate-400">
        <div className="w-8 h-8 border-2 border-sky-400 border-t-transparent rounded-full animate-spin mb-3" />
        <div className="text-sm font-medium">Loading topology…</div>
      </div>
    );
  }

  if (!bounds) {
    return (
      <div className="relative isolate w-full h-full min-h-[480px] bg-[#050d1a] flex flex-col items-center justify-center text-slate-400 p-6 text-center">
        <div className="text-3xl mb-2">🗺️</div>
        <div className="text-sm font-medium text-slate-200 mb-1">
          No geographic data from the backend
        </div>
        <div className="text-xs text-slate-500 max-w-sm">
          Topology is loaded, but no nodes have valid latitude and longitude coordinates.
        </div>
      </div>
    );
  }

  const defaultCenter = [
    (bounds[0][0] + bounds[1][0]) / 2,
    (bounds[0][1] + bounds[1][1]) / 2,
  ];

  const label = telemetryLabel(dataSource);

  return (
    <div className="relative isolate w-full h-full min-h-[480px] bg-[#050d1a] overflow-hidden select-none">
      {/* Honesty Chip */}
      <div
        role="note"
        aria-label="Telemetry data source"
        className="absolute top-3 right-3 z-[1000] bg-slate-900/90 backdrop-blur-sm border border-slate-700/70 text-slate-300 text-[11px] sm:text-xs px-2.5 py-1.5 rounded shadow pointer-events-none flex items-center gap-2 max-w-[calc(100%-1rem)] sm:max-w-max leading-tight"
      >
        <span className="w-2 h-2 rounded-full bg-emerald-400 shrink-0" />
        <span>
          {label
            ? `${label} · illustrative placement · source: ${dataSource}`
            : `illustrative placement · source: ${dataSource}`}
        </span>
      </div>

      {/* Offline Status Chip */}
      {isOffline && (
        <div
          role="status"
          className="absolute top-20 left-3 z-[1000] bg-amber-950/90 backdrop-blur-sm border border-amber-600/70 text-amber-200 text-xs px-2.5 py-1.5 rounded shadow pointer-events-none flex items-center gap-1.5"
        >
          <span className="text-amber-400 font-bold">⚠</span>
          <span>Basemap offline: showing network only</span>
        </div>
      )}

      {/* Map Legend */}
      <Legend />

      <MapContainer
        center={defaultCenter}
        zoom={12}
        zoomControl={true}
        attributionControl={true}
        className="w-full h-full z-0"
        style={{ background: '#050d1a' }}
      >
        <TileLayer
          ref={tileLayerRef}
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          subdomains="abcd"
          maxZoom={19}
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
          errorTileUrl={ERROR_TILE_URL}
          eventHandlers={{
            tileerror: () => setIsOffline(true),
            tileload: (e) => {
              const src = e?.tile?.src;
              if (src && src !== ERROR_TILE_URL) {
                setIsOffline(false);
              }
            },
          }}
        />

        <ScaleControl position="bottomright" imperial={false} />
        <MapResizer />
        <FitBoundsOnce bounds={bounds} />
      </MapContainer>
    </div>
  );
}
