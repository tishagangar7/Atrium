import { useEffect, useRef } from "react";
import { Icon } from "./Icon";
export function Inspector({
  title,
  value,
  onClose,
}: {
  title: string;
  value: unknown;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    const trigger = document.activeElement as HTMLElement | null;
    dialog.showModal();
    return () => {
      dialog.close();
      trigger?.focus();
    };
  }, []);
  return (
    <dialog
      className="inspector"
      ref={ref}
      onCancel={onClose}
      aria-labelledby="inspector-title"
    >
      <div className="inspector-heading">
        <h2 id="inspector-title">{title}</h2>
        <button
          className="icon-button"
          aria-label="Close inspector"
          onClick={onClose}
        >
          <Icon name="close" />
        </button>
      </div>
      {typeof value === "string" ? (
        <p>{value}</p>
      ) : (
        <pre>{JSON.stringify(value, null, 2)}</pre>
      )}
      <div className="inspector-footer">Synthetic simulation</div>
    </dialog>
  );
}
