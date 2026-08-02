/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./app/**/*.{js,jsx,ts,tsx}', './src/**/*.{js,jsx,ts,tsx}'],
  presets: [require('nativewind/preset')],
  theme: {
    extend: {
      colors: {
        // Ink over pure black: pure black on an OLED phone in sunlight
        // vibrates against the white surface and tires the eye.
        ink: {
          DEFAULT: '#16181d',
          muted: '#5b6472',
          faint: '#8b95a5',
        },
        surface: {
          DEFAULT: '#ffffff',
          sunken: '#f4f6f9',
          raised: '#ffffff',
          border: '#e2e6ec',
        },
        // Deep indigo rather than the default blue-600: it holds contrast
        // against white in direct daylight, where a brighter blue washes out.
        brand: {
          DEFAULT: '#2c3ea8',
          pressed: '#22307f',
          wash: '#eef1fb',
        },
        positive: { DEFAULT: '#1f6f4a', wash: '#e8f4ee' },
        caution: { DEFAULT: '#8a5a10', wash: '#fdf3e2' },
        critical: { DEFAULT: '#a32828', wash: '#fbeceb' },
      },
      spacing: {
        // Touch target floor. Android accessibility minimum is 48dp; every
        // interactive element uses this rather than an arbitrary padding.
        touch: '48px',
      },
      borderRadius: {
        card: '14px',
        control: '10px',
      },
      fontSize: {
        // Steps are deliberately far apart so hierarchy survives the
        // system font-scale settings students actually run.
        display: ['30px', { lineHeight: '36px', letterSpacing: '-0.5px' }],
        title: ['21px', { lineHeight: '27px', letterSpacing: '-0.3px' }],
        heading: ['17px', { lineHeight: '23px' }],
        body: ['15px', { lineHeight: '22px' }],
        detail: ['13px', { lineHeight: '18px' }],
        label: ['11px', { lineHeight: '15px', letterSpacing: '0.6px' }],
      },
    },
  },
  plugins: [],
};
