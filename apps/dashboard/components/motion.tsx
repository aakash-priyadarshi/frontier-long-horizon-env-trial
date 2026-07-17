"use client";

import {
  AnimatePresence,
  MotionConfig,
  animate,
  motion,
  useReducedMotion,
} from "motion/react";
import { ChevronDown } from "lucide-react";
import {
  Children,
  type ComponentProps,
  type ReactNode,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";

export const motionTransition = {
  duration: 0.2,
  ease: [0.22, 1, 0.36, 1] as [number, number, number, number],
};

export const layoutTransition = {
  duration: 0.3,
  ease: [0.22, 1, 0.36, 1] as [number, number, number, number],
};

export function MotionProvider({ children }: { children: ReactNode }) {
  return <MotionConfig reducedMotion="user" transition={motionTransition}>{children}</MotionConfig>;
}

export function PageTransition({ children, routeKey }: { children: ReactNode; routeKey: string }) {
  const reduce = useReducedMotion();
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={routeKey}
        initial={reduce ? false : { opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={reduce ? { opacity: 1 } : { opacity: 0, y: -4 }}
        transition={reduce ? { duration: 0.01 } : motionTransition}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

export function AnimatedCard({
  children,
  className = "",
  as = "article",
}: {
  children: ReactNode;
  className?: string;
  as?: "article" | "section" | "div";
}) {
  const reduce = useReducedMotion();
  const Component = motion[as];
  return (
    <Component
      className={className}
      layout={!reduce}
      whileHover={reduce ? undefined : { y: -3, scale: 1.005 }}
      transition={motionTransition}
    >
      {children}
    </Component>
  );
}

export function AnimatedNumber({
  value,
  format = valueToFormat => String(Math.round(valueToFormat)),
}: {
  value: number | null | undefined;
  format?: (value: number) => string;
}) {
  const numeric = value ?? 0;
  const reduce = useReducedMotion();
  const previous = useRef(numeric);
  const [display, setDisplay] = useState(numeric);

  useEffect(() => {
    const start = previous.current;
    previous.current = numeric;
    if (reduce) {
      setDisplay(numeric);
      return;
    }
    const controls = animate(start, numeric, {
      duration: 0.32,
      ease: motionTransition.ease,
      onUpdate: setDisplay,
    });
    return () => controls.stop();
  }, [numeric, reduce]);

  return <span aria-label={format(numeric)}>{value == null ? "—" : format(display)}</span>;
}

export function AnimatedStatus({ children, state }: { children: ReactNode; state: string }) {
  const reduce = useReducedMotion();
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.span
        key={state}
        className="animated-status"
        initial={reduce ? false : { opacity: 0, y: 3 }}
        animate={{ opacity: 1, y: 0 }}
        exit={reduce ? { opacity: 1 } : { opacity: 0, y: -3 }}
      >
        {children}
      </motion.span>
    </AnimatePresence>
  );
}

export function ExpandablePanel({
  summary,
  children,
  defaultOpen = false,
  className = "",
}: {
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const reduce = useReducedMotion();
  const id = useId();
  return (
    <div className={`expandable-panel ${className}`}>
      <button type="button" className="expandable-trigger" aria-expanded={open} aria-controls={id} onClick={() => setOpen(value => !value)}>
        {summary}
        <motion.span aria-hidden="true" animate={{ rotate: open && !reduce ? 180 : 0 }}><ChevronDown size={16} /></motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={id}
            className="expandable-content"
            initial={reduce ? false : { height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }}
            transition={reduce ? { duration: 0.01 } : layoutTransition}
          >
            {children}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function StaggeredList({ children, className = "" }: { children: ReactNode; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      variants={{ show: { transition: { staggerChildren: reduce ? 0 : 0.045 } } }}
      initial="hidden"
      animate="show"
    >
      {Children.map(children, child => (
        <motion.div variants={{ hidden: reduce ? { opacity: 1 } : { opacity: 0, y: 6 }, show: { opacity: 1, y: 0 } }}>{child}</motion.div>
      ))}
    </motion.div>
  );
}

export function SharedSelectionIndicator({ layoutId }: { layoutId: string }) {
  return <motion.span className="shared-selection-indicator" layoutId={layoutId} transition={layoutTransition} aria-hidden="true" />;
}

type MotionButtonProps = Omit<ComponentProps<typeof motion.button>, "children"> & {
  children: ReactNode;
};

export function MotionButton({ children, className = "", type = "button", ...props }: MotionButtonProps) {
  return (
    <motion.button
      type={type}
      className={className}
      whileHover={props.disabled ? undefined : { y: -2, scale: 1.005 }}
      whileTap={props.disabled ? undefined : { scale: 0.98 }}
      transition={motionTransition}
      {...props}
    >
      {children}
    </motion.button>
  );
}
