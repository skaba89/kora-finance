/** First keyboard stop; the target is focusable but is not in the tab order. */
export function SkipLink({ label }: { label: string }) {
  return (
    <a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-lg focus:bg-card focus:px-4 focus:py-3 focus:text-primary focus:shadow-lg">
      {label}
    </a>
  );
}
