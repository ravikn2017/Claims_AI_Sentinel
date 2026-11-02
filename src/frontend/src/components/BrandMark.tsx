import styles from "./BrandMark.module.css";

export function BrandMark() {
  return (
    <span className={styles.mark} aria-hidden="true">
      <svg className={styles.glyph} viewBox="0 0 24 24">
        <path
          fill="currentColor"
          d="M12 1.6 4 4.9v6.5c0 4.8 3.3 9.1 8 10.8 4.7-1.7 8-6 8-10.8V4.9L12 1.6z"
        />
        <path
          fill="var(--mui-palette-brand-contrastText)"
          d="M10.7 15.2 7.8 12.3l-1.2 1.2 4.1 4.1 6.8-6.8-1.2-1.2z"
        />
      </svg>
    </span>
  );
}
