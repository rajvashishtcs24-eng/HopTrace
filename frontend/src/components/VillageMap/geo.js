/**
 * Pure geographic utility functions for HopTrace VillageMap.
 */

/**
 * Computes bounding box [[minLat, minLon], [maxLat, maxLon]] for an array of nodes.
 * Only nodes with finite numeric `lat` and `lon` are considered.
 * Returns null if no valid coordinates exist.
 *
 * @param {Array<{lat?: number, lon?: number}>} nodes
 * @returns {[[number, number], [number, number]] | null}
 */
export function computeBounds(nodes) {
  if (!Array.isArray(nodes) || nodes.length === 0) {
    return null;
  }

  let minLat = Infinity;
  let maxLat = -Infinity;
  let minLon = Infinity;
  let maxLon = -Infinity;
  let count = 0;

  for (const node of nodes) {
    if (!node || typeof node !== 'object') continue;
    const { lat, lon } = node;
    if (Number.isFinite(lat) && Number.isFinite(lon)) {
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      count++;
    }
  }

  if (count === 0) {
    return null;
  }

  return [
    [minLat, minLon],
    [maxLat, maxLon],
  ];
}
