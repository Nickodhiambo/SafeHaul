import { useEffect, useId, useRef, useState } from "react";
import { geocode, isAbort } from "../api/client";
import type { Place } from "../api/types";
import { useDebounce } from "../hooks/useDebounce";

interface Props {
  label: string;
  placeholder: string;
  value: string;
  selected: Place | null;
  /** Called on every edit (place = null) and when a suggestion is picked. */
  onChange: (text: string, place: Place | null) => void;
  error?: string;
  marker: "A" | "B";
}

const MIN_CHARS = 2;
const DEBOUNCE_MS = 300;

/**
 * Autocomplete combobox. Keystrokes are debounced and any in-flight search is cancelled
 * when a newer one starts, so slow responses can never overwrite fresh ones.
 */
export function PlaceInput({ label, placeholder, value, selected, onChange, error, marker }: Props) {
  const uid = useId();
  const listId = `${uid}-list`;
  const [items, setItems] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [failed, setFailed] = useState(false);
  const blurTimer = useRef<number | undefined>(undefined);

  const query = useDebounce(value.trim(), DEBOUNCE_MS);

  useEffect(() => {
    if (selected || query.length < MIN_CHARS) {
      setItems([]);
      setLoading(false);
      setSearched(false);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    setFailed(false);
    geocode(query, ctrl.signal)
      .then((results) => {
        setItems(results);
        setActive(-1);
        setSearched(true);
        setLoading(false);
      })
      .catch((e) => {
        if (isAbort(e)) return;
        setItems([]);
        setFailed(true);
        setSearched(true);
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [query, selected]);

  useEffect(() => () => window.clearTimeout(blurTimer.current), []);

  const pick = (place: Place) => {
    onChange(place.label, place);
    setOpen(false);
    setItems([]);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" && items.length) {
      e.preventDefault();
      setOpen(true);
      setActive((i) => (i + 1) % items.length);
    } else if (e.key === "ArrowUp" && items.length) {
      e.preventDefault();
      setActive((i) => (i <= 0 ? items.length - 1 : i - 1));
    } else if (e.key === "Enter" && open && active >= 0 && items[active]) {
      e.preventDefault();
      pick(items[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const showList = open && !selected && value.trim().length >= MIN_CHARS && (loading || searched);
  const inputId = `${uid}-input`;

  return (
    <div className="field">
      <label htmlFor={inputId} className="field-label">
        <span className={`pin-badge pin-${marker.toLowerCase()}`} aria-hidden="true">
          {marker}
        </span>
        {label}
      </label>
      <div className="combo">
        <input
          id={inputId}
          className={`input${error ? " input-error" : ""}`}
          type="text"
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? `${uid}-opt-${active}` : undefined}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${uid}-err` : undefined}
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          placeholder={placeholder}
          value={value}
          onChange={(e) => {
            onChange(e.target.value, null);
            setOpen(true);
          }}
          onFocus={() => {
            window.clearTimeout(blurTimer.current);
            setOpen(true);
          }}
          onBlur={() => {
            blurTimer.current = window.setTimeout(() => setOpen(false), 120);
          }}
          onKeyDown={onKeyDown}
        />
        {loading && <span className="spinner spinner-sm combo-spinner" aria-label="Searching" />}
        {showList && (
          <ul id={listId} role="listbox" className="suggestions">
            {items.map((p, i) => (
              <li
                key={p.id}
                id={`${uid}-opt-${i}`}
                role="option"
                aria-selected={i === active}
                className={`suggestion${i === active ? " is-active" : ""}`}
                // pointerdown (not click) so the pick lands before the input's blur closes the list
                onPointerDown={(e) => {
                  e.preventDefault();
                  pick(p);
                }}
                onMouseEnter={() => setActive(i)}
              >
                {p.label}
              </li>
            ))}
            {!loading && items.length === 0 && (
              <li className="suggestion suggestion-empty" role="presentation">
                {failed ? "Place search is unavailable right now. You can still type the full name." : "No matches found"}
              </li>
            )}
          </ul>
        )}
      </div>
      {error && (
        <p id={`${uid}-err`} className="field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
