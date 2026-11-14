import { Link } from "react-router-dom";

const VARIANTS = {
  primary: "border-primary text-primary hover:bg-primary hover:text-black",
  solid: "border-primary bg-primary text-black hover:bg-transparent hover:text-primary",
  danger: "border-danger text-danger hover:bg-danger hover:text-black",
  ghost: "border-edge text-textColor hover:border-primary hover:text-primary",
};

export default function Button({ href, variant = "primary", className = "", children, ...rest }) {
  const cls = `inline-flex min-h-[44px] items-center justify-center gap-2 rounded-md border px-6 py-2.5 font-mono text-sm uppercase tracking-wider transition-colors duration-200 disabled:pointer-events-none disabled:opacity-40 ${VARIANTS[variant]} ${className}`;
  const content = (<><span className="opacity-60" aria-hidden="true">&gt;</span>{children}</>);
  return href ? (
    <Link to={href} className={cls} {...rest}>{content}</Link>
  ) : (
    <button type="button" className={cls} {...rest}>{content}</button>
  );
}
