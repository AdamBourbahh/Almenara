import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "ghost" | "outline" | "danger";
type Size = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
}

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-[transform,background-color,border-color,color] duration-150 ease-[var(--ease-out)] active:scale-[0.97] disabled:pointer-events-none disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ember/60";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-ember text-[#1c0d07] hover:bg-[#ff7d55] shadow-[0_12px_34px_-14px_rgba(255,107,61,0.75)]",
  ghost: "text-dim hover:bg-white/5 hover:text-ink",
  outline: "border border-line bg-white/[0.02] text-ink hover:bg-white/[0.06]",
  danger:
    "border border-danger/30 bg-danger/15 text-danger hover:bg-danger/25",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-xs",
  md: "h-10 px-4 text-sm",
};

export function Button({
  variant = "outline",
  size = "md",
  icon,
  className = "",
  children,
  ...rest
}: ButtonProps) {
  return (
    <button className={`${BASE} ${VARIANTS[variant]} ${SIZES[size]} ${className}`} {...rest}>
      {icon}
      {children}
    </button>
  );
}
