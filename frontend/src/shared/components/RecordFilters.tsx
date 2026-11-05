export function RecordFilters<T extends string>({ label, value, options, onChange }: {
  label: string;
  value: T;
  options: readonly { id: T; label: string; count: number }[];
  onChange: (value: T) => void;
}) {
  return <div className="record-filters" role="group" aria-label={label}>
    {options.map((option) => <button key={option.id} type="button" aria-pressed={value === option.id}
      onClick={() => onChange(option.id)}>
      {option.label} <span>{option.count}</span>
    </button>)}
  </div>;
}
