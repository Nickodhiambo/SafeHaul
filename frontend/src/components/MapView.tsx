import mapboxgl, { type GeoJSONSource, type Map as MapboxMap, type MapMouseEvent } from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { AnalyzeResponse, HeatmapResponse } from "../api/types";
import { checkpointFeatures, heatFeatures, routeBounds, routeFeatures } from "../lib/geo";
import { addHours, formatDayTime } from "../lib/time";
import { addMapLayers, LAYER, SRC } from "./mapLayers";
import { checkpointPopup, heatPopup } from "./mapPopups";

const TOKEN = import.meta.env.VITE_MAPBOX_TOKEN;
const STYLE = "mapbox://styles/mapbox/light-v11";
const DESKTOP_MIN_WIDTH = 900;

export interface MapFocus {
  routeId: string;
  index: number;
  nonce: number; // changes on every request so re-focusing the same row works
}

interface Props {
  analysis: AnalyzeResponse | null;
  selectedId: string | null;
  onSelectRoute: (id: string) => void;
  heat: HeatmapResponse | undefined;
  hour: number;
  showHeat: boolean;
  focus: MapFocus | null;
  /** False while the map's tab is hidden (mobile); triggers a resize when it becomes visible. */
  visible: boolean;
}

const fitPadding = () =>
  window.innerWidth >= DESKTOP_MIN_WIDTH
    ? { top: 70, bottom: 190, left: 450, right: 60 } // left panel + slider overlay
    : { top: 70, bottom: 200, left: 30, right: 30 };

function pinElement(letter: "A" | "B"): HTMLElement {
  const node = document.createElement("div");
  node.className = `map-pin pin-${letter.toLowerCase()}`;
  node.textContent = letter;
  return node;
}

export default function MapView(props: Props) {
  const { analysis, selectedId, heat, hour, showHeat, focus, visible } = props;
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapboxMap | null>(null);
  const popupRef = useRef<mapboxgl.Popup | null>(null);
  const pinsRef = useRef<mapboxgl.Marker[]>([]);
  const [ready, setReady] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);

  // Event handlers are registered once, so they read the latest props through a ref.
  const latest = useRef(props);
  useLayoutEffect(() => {
    latest.current = props;
  });

  const showPopup = (lngLat: [number, number], content: HTMLElement) => {
    const map = mapRef.current;
    if (!map) return;
    popupRef.current?.remove();
    popupRef.current = new mapboxgl.Popup({ closeButton: true, maxWidth: "280px", offset: 12 })
      .setLngLat(lngLat)
      .setDOMContent(content)
      .addTo(map);
  };

  // --- create the map once ----------------------------------------------------------------
  useEffect(() => {
    if (!TOKEN || !containerRef.current) return;
    mapboxgl.accessToken = TOKEN;
    let map: MapboxMap;
    try {
      map = new mapboxgl.Map({
        container: containerRef.current,
        style: STYLE,
        center: [-96, 38.5],
        zoom: 3.4,
        attributionControl: true,
      });
    } catch {
      setMapError("The map couldn't start. Your browser may not support WebGL, or it is turned off.");
      return;
    }
    mapRef.current = map;
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right");

    let loaded = false;
    map.on("load", () => {
      loaded = true;
      addMapLayers(map);
      wireInteractions(map);
      setReady(true);
    });
    map.on("error", (e) => {
      const status = (e.error as { status?: number } | undefined)?.status;
      if (status === 401 || status === 403) setMapError("The map couldn't load: the Mapbox token was rejected.");
      else if (!loaded) setMapError("The map couldn't load. Check your connection and that WebGL is enabled.");
    });

    const observer = new ResizeObserver(() => map.resize());
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      popupRef.current?.remove();
      pinsRef.current.forEach((p) => p.remove());
      pinsRef.current = [];
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function wireInteractions(map: MapboxMap) {
    const pointer = (layer: string) => {
      map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
    };
    [LAYER.routeHit, LAYER.checkpoints, LAYER.heatPoints].forEach(pointer);

    // Checkpoints and heat points sit above the route, so they get first claim on a tap
    map.on("click", LAYER.checkpoints, (e: MapMouseEvent) => {
      const f = e.features?.[0];
      if (!f) return;
      const { analysis: a } = latest.current;
      const route = a?.routes.find((r) => r.id === f.properties?.routeId);
      const cp = route?.checkpoints[Number(f.properties?.index)];
      if (cp) showPopup([cp.lon, cp.lat], checkpointPopup(cp));
    });
    map.on("click", LAYER.heatPoints, (e: MapMouseEvent) => {
      const f = e.features?.[0];
      const { heat: h, hour: hr } = latest.current;
      const point = h?.points[Number(f?.properties?.i)];
      if (!f || !h || !point) return;
      const hourClamped = Math.min(hr, h.hours);
      showPopup([point.lon, point.lat], heatPopup(point, hourClamped, formatDayTime(addHours(h.start, hourClamped))));
    });
    map.on("click", LAYER.routeHit, (e: MapMouseEvent) => {
      const hitDot = map.queryRenderedFeatures(e.point, { layers: [LAYER.checkpoints, LAYER.heatPoints] });
      if (hitDot.length) return;
      const id = e.features?.[0]?.properties?.id;
      if (typeof id === "string") latest.current.onSelectRoute(id);
    });
  }

  // --- routes + checkpoints ---------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const routes = analysis?.routes ?? [];
    (map.getSource(SRC.routes) as GeoJSONSource).setData(routeFeatures(routes, selectedId) as never);
    (map.getSource(SRC.checkpoints) as GeoJSONSource).setData(
      checkpointFeatures(routes.find((r) => r.id === selectedId)) as never,
    );
    popupRef.current?.remove();
  }, [ready, analysis, selectedId]);

  // --- A/B pins for each new analysis -----------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    pinsRef.current.forEach((p) => p.remove());
    pinsRef.current = [];
    if (!analysis) return;

    const { origin, destination } = analysis.request;
    pinsRef.current = [
      new mapboxgl.Marker({ element: pinElement("A") }).setLngLat([origin.lon, origin.lat]).addTo(map),
      new mapboxgl.Marker({ element: pinElement("B") }).setLngLat([destination.lon, destination.lat]).addTo(map),
    ];
  }, [ready, analysis]);

  // --- zoom to fit all routes, once per analysis, and only while the map is visible --------
  // (On phones the map's tab is hidden when results arrive; fitting a 0x0 container gives a
  // nonsense zoom, so the fit waits until the tab is shown.)
  const fittedFor = useRef<AnalyzeResponse | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !analysis || !visible || fittedFor.current === analysis) return;
    const bounds = routeBounds(analysis.routes);
    if (!bounds) return;
    map.resize();
    map.fitBounds(bounds, { padding: fitPadding(), duration: 900, maxZoom: 12 });
    fittedFor.current = analysis;
  }, [ready, analysis, visible]);

  // --- heatmap frame: just swap the data, never rebuild layers ----------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource(SRC.heat) as GeoJSONSource).setData(heatFeatures(heat, hour) as never);
  }, [ready, heat, hour]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const visibility = showHeat ? "visible" : "none";
    map.setLayoutProperty(LAYER.heatmap, "visibility", visibility);
    map.setLayoutProperty(LAYER.heatPoints, "visibility", visibility);
  }, [ready, showHeat]);

  // --- "show on map" from the checkpoint list ----------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !focus) return;
    const cp = analysis?.routes.find((r) => r.id === focus.routeId)?.checkpoints[focus.index];
    if (!cp) return;
    map.flyTo({ center: [cp.lon, cp.lat], zoom: Math.max(map.getZoom(), 8.5), duration: 700 });
    showPopup([cp.lon, cp.lat], checkpointPopup(cp));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus]);

  useEffect(() => {
    if (visible) mapRef.current?.resize();
  }, [visible]);

  if (!TOKEN || mapError) {
    return (
      <div className="map-fallback" role="alert">
        <strong>Map unavailable</strong>
        <p>
          {mapError ??
            "Add your Mapbox public token as VITE_MAPBOX_TOKEN in frontend/.env (or in your host's environment variables), then restart."}
        </p>
      </div>
    );
  }
  return <div ref={containerRef} className="map" aria-label="Route map" />;
}
