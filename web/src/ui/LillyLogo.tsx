import React from 'react'

interface LillyLogoProps extends React.SVGProps<SVGSVGElement> {
  size?: number | string
  monochrome?: boolean
}

export const LillyLogo: React.FC<LillyLogoProps> = ({
  size = 28,
  monochrome = false,
  className = '',
  ...props
}) => {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 36 36"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      {...props}
    >
      <defs>
        <linearGradient id="lilly-grad-main" x1="4" y1="4" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop stopColor="var(--accent-lime, #d4ee38)" />
          <stop offset="0.6" stopColor="var(--pastel-periwinkle-bg, #b8c2f8)" />
          <stop offset="1" stopColor="var(--pastel-lilac-bg, #f5c7e6)" />
        </linearGradient>
        <linearGradient id="lilly-grad-accent" x1="18" y1="6" x2="18" y2="30" gradientUnits="userSpaceOnUse">
          <stop stopColor="#1c1c1e" />
          <stop offset="1" stopColor="#3a3a3c" />
        </linearGradient>
      </defs>

      {/* Floating Base Leaf / Ripple */}
      <path
        d="M6 27.5C10 29.5 14 30.5 18 30.5C22 30.5 26 29.5 30 27.5C28.5 28.8 24 31 18 31C12 31 7.5 28.8 6 27.5Z"
        fill={monochrome ? 'currentColor' : 'var(--text-muted)'}
        opacity={0.35}
      />

      {/* Left Petal */}
      <path
        d="M18 27C14.5 26 8 21.5 8 15C8 10.5 12 8 14 12C15.5 15 17 21 18 27Z"
        fill={monochrome ? 'currentColor' : 'url(#lilly-grad-main)'}
        opacity={0.9}
      />

      {/* Right Petal */}
      <path
        d="M18 27C21.5 26 28 21.5 28 15C28 10.5 24 8 22 12C20.5 15 19 21 18 27Z"
        fill={monochrome ? 'currentColor' : 'url(#lilly-grad-main)'}
        opacity={0.9}
      />

      {/* Center Lily Petal */}
      <path
        d="M18 5.5C18 5.5 22.5 13 22.5 19.5C22.5 24 20.5 27 18 27C15.5 27 13.5 24 13.5 19.5C13.5 13 18 5.5 18 5.5Z"
        fill={monochrome ? 'currentColor' : 'var(--text-main)'}
      />

      {/* Core Glow / Seed Stamen */}
      <circle
        cx="18"
        cy="20.5"
        r="2"
        fill={monochrome ? 'var(--bg-app)' : 'var(--accent-lime, #d4ee38)'}
      />
    </svg>
  )
}
