import { useMemo, useState, type FormEvent } from 'react';
import { motion } from 'motion/react';
import type { WidgetMaterialEvent } from '@/types/sse';
import type { MaterialSlotMapping } from '@/types/api';
import { CONNECTED_NO_IMAGE, PRINCIPLED_SLOTS, type PrincipledSlot } from '@/types/domain';
import styles from './MaterialWidget.module.css';

interface MaterialWidgetProps {
  event: WidgetMaterialEvent;
  onSubmit: (payload: MaterialSlotMapping[], summary: string) => void;
}

// Pre-fill precedence: LLM suggestion > existing wired (unless connected_no_image) > empty.
// Experimental suggestions (issue #22 Stage 3) are NEVER auto-applied — user must
// click the explicit "Apply" button next to each experimental row.
function pickInitial(
  mat: string,
  slot: PrincipledSlot,
  event: WidgetMaterialEvent,
): string {
  const suggested = event.suggestions[mat]?.[slot];
  if (suggested) return suggested;
  const existing = event.existing_connections[mat]?.[slot];
  if (existing && existing !== CONNECTED_NO_IMAGE) return existing;
  return '';
}

function basename(path: string): string {
  const i = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
  return i >= 0 ? path.slice(i + 1) : path;
}

export function MaterialWidget({ event, onSubmit }: MaterialWidgetProps) {
  const initial = useMemo(() => {
    const out: Record<string, Partial<Record<PrincipledSlot, string>>> = {};
    for (const mat of event.materials) {
      out[mat] = {};
      for (const slot of PRINCIPLED_SLOTS) {
        out[mat][slot] = pickInitial(mat, slot, event);
      }
    }
    return out;
  }, [event]);
  const [values, setValues] = useState(initial);
  const [pending, setPending] = useState(false);

  const setSlot = (mat: string, slot: PrincipledSlot, value: string) => {
    setValues((prev) => ({ ...prev, [mat]: { ...prev[mat], [slot]: value } }));
  };

  const handleSubmit = (ev: FormEvent<HTMLFormElement>) => {
    ev.preventDefault();
    if (pending) return;
    const mappings: MaterialSlotMapping[] = [];
    for (const mat of event.materials) {
      for (const slot of PRINCIPLED_SLOTS) {
        const path = values[mat]?.[slot] ?? '';
        if (path) mappings.push({ material: mat, slot, texture_path: path });
      }
    }
    setPending(true);
    onSubmit(mappings, `[Confirmed ${mappings.length} slot assignments]`);
  };

  const visionSlots = event.vision_suggested_slots ?? {};
  const experimental = event.experimental_suggestions ?? {};
  const hasExperimental = Object.values(experimental).some(
    (rows) => rows && Object.keys(rows).length > 0,
  );

  return (
    <motion.form
      className={`${styles.form} ${pending ? styles.pending : ''}`}
      onSubmit={handleSubmit}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.2 }}
    >
      <header className={styles.header}>
        <h3>Confirm texture mapping</h3>
        <span className={styles.hint}>
          Rows marked <span className={styles.suggestedChip}>LLM</span> are pre-filled by
          the filename agent;{' '}
          <span className={styles.visionChip}>VLM</span> rows came from the vision model
          (please double-check). Leave a slot blank to skip it.
        </span>
      </header>

      {event.materials.map((mat) => {
        const matVisionSlots = new Set(visionSlots[mat] ?? []);
        const matExperimental = experimental[mat] ?? {};
        const hasMatExperimental = Object.keys(matExperimental).length > 0;
        return (
          <details key={mat} className={styles.materialBlock} open>
            <summary className={styles.materialHeader}>{mat}</summary>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Slot</th>
                  <th>Texture</th>
                </tr>
              </thead>
              <tbody>
                {PRINCIPLED_SLOTS.map((slot) => {
                  const suggested = event.suggestions[mat]?.[slot];
                  const isVision = matVisionSlots.has(slot);
                  const isSuggested = !!suggested;
                  const value = values[mat]?.[slot] ?? '';
                  return (
                    <tr
                      key={`${mat}::${slot}`}
                      className={
                        isVision
                          ? styles.rowVision
                          : isSuggested
                            ? styles.rowSuggested
                            : ''
                      }
                    >
                      <td className={styles.slotName}>
                        {slot}
                        {isVision ? (
                          <span
                            className={styles.visionChip}
                            title="Filled by the vision model — please verify"
                          >
                            VLM
                          </span>
                        ) : isSuggested ? (
                          <span className={styles.suggestedChip} title="Pre-filled by LLM">
                            LLM
                          </span>
                        ) : null}
                      </td>
                      <td>
                        <select
                          value={value}
                          onChange={(e) => setSlot(mat, slot, e.target.value)}
                        >
                          <option value="">(none)</option>
                          {event.texture_files.map((tex) => (
                            <option key={tex} value={tex}>
                              {basename(tex)}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {hasMatExperimental && (
              <div className={styles.experimentalBlock}>
                <div className={styles.experimentalHeader}>
                  <span className={styles.experimentalChip}>EXPERIMENTAL</span>
                  <span className={styles.experimentalHint}>
                    Reverse-inference suggestions from the vision model — never
                    auto-applied. Click <em>Apply</em> to use one.
                  </span>
                </div>
                <ul className={styles.experimentalList}>
                  {(Object.entries(matExperimental) as [PrincipledSlot, string][])
                    .filter(([, fp]) => !!fp)
                    .map(([slot, fp]) => (
                      <li key={`${mat}-exp-${slot}`}>
                        <span className={styles.experimentalSlot}>{slot}</span>
                        <span className={styles.experimentalFile}>{basename(fp)}</span>
                        <button
                          type="button"
                          className={styles.experimentalApplyBtn}
                          disabled={pending}
                          onClick={() => setSlot(mat, slot, fp)}
                        >
                          Apply
                        </button>
                      </li>
                    ))}
                </ul>
              </div>
            )}
          </details>
        );
      })}

      <div className={styles.actions}>
        {hasExperimental && (
          <span className={styles.experimentalGlobalHint}>
            ⚠ Experimental suggestions present — review and apply per slot.
          </span>
        )}
        <button type="submit" className={styles.submitBtn} disabled={pending}>
          {pending ? 'Submitted — waiting for agent…' : 'Confirm material mapping'}
        </button>
      </div>
    </motion.form>
  );
}
