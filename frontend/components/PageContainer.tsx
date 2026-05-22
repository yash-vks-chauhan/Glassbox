import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type PageContainerProps = {
  children: ReactNode;
  className?: string;
  size?: "default" | "wide" | "full";
};

export function PageContainer({ children, className, size = "default" }: PageContainerProps) {
  return (
    <div
      className={cn(
        "mx-auto w-full px-5 py-6 lg:px-8 lg:py-8",
        size === "default" && "max-w-[1240px]",
        size === "wide" && "max-w-[1480px]",
        size === "full" && "max-w-none",
        className,
      )}
    >
      {children}
    </div>
  );
}

type PageHeaderProps = {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
};

export function PageHeader({ eyebrow, title, description, actions, className }: PageHeaderProps) {
  return (
    <div className={cn("mb-6 flex flex-col gap-3 lg:mb-8 lg:flex-row lg:items-end lg:justify-between", className)}>
      <div className="space-y-2">
        {eyebrow ? (
          <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
            {eyebrow}
          </div>
        ) : null}
        <h1 className="font-serif text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
          {title}
        </h1>
        {description ? (
          <p className="max-w-2xl text-sm leading-6 text-muted-foreground sm:text-[15px] sm:leading-7">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
