// One authored icon set: 16px grid, 1.75 stroke, round caps.
import type { SVGProps } from "react";

function Svg({ children, ...p }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 16 16"
      width={16}
      height={16}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...p}
    >
      {children}
    </svg>
  );
}

export const IconCheck = (p: SVGProps<SVGSVGElement>) => (
  <Svg {...p}>
    <path d="M3.5 8.5l3 3 6-7" />
  </Svg>
);
export const IconX = (p: SVGProps<SVGSVGElement>) => (
  <Svg {...p}>
    <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />
  </Svg>
);
export const IconMinus = (p: SVGProps<SVGSVGElement>) => (
  <Svg {...p}>
    <path d="M4.5 8h7" />
  </Svg>
);
export const IconAlert = (p: SVGProps<SVGSVGElement>) => (
  <Svg {...p}>
    <path d="M8 2.5l6 10.5H2L8 2.5z" />
    <path d="M8 6.5v3" />
    <path d="M8 11.4v.1" />
  </Svg>
);
export const IconShield = (p: SVGProps<SVGSVGElement>) => (
  <Svg {...p}>
    <path d="M8 1.75l5 2v4c0 3-2.2 5.3-5 6.5-2.8-1.2-5-3.5-5-6.5v-4l5-2z" />
    <path d="M8 5.25v3.25" />
    <path d="M8 10.6v.1" />
  </Svg>
);
export const IconClock = (p: SVGProps<SVGSVGElement>) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="5.75" />
    <path d="M8 5v3.25l2 1.25" />
  </Svg>
);
export const IconUpload = (p: SVGProps<SVGSVGElement>) => (
  <Svg {...p}>
    <path d="M8 10.5V2.75M4.75 6L8 2.75 11.25 6" />
    <path d="M2.75 10.5v1.75c0 .55.45 1 1 1h8.5c.55 0 1-.45 1-1V10.5" />
  </Svg>
);
export const IconDoc = (p: SVGProps<SVGSVGElement>) => (
  <Svg {...p}>
    <path d="M4 1.75h5l3 3v9.5H4z" />
    <path d="M9 1.75v3h3M6 8.5h4M6 11h4" />
  </Svg>
);
export const IconRerun = (p: SVGProps<SVGSVGElement>) => (
  <Svg {...p}>
    <path d="M13 8a5 5 0 1 1-1.6-3.7" />
    <path d="M13 2.75v2.75h-2.75" />
  </Svg>
);
export const IconChevron = (p: SVGProps<SVGSVGElement>) => (
  <Svg {...p}>
    <path d="M6 4l4 4-4 4" />
  </Svg>
);
export const IconArrow = (p: SVGProps<SVGSVGElement>) => (
  <Svg {...p}>
    <path d="M3 8h10M9.5 4.5L13 8l-3.5 3.5" />
  </Svg>
);
export const IconSpinner = (p: SVGProps<SVGSVGElement>) => (
  <Svg {...p} className={`anim-spin ${p.className ?? ""}`}>
    <path d="M8 2.25a5.75 5.75 0 1 1-5.75 5.75" />
  </Svg>
);
