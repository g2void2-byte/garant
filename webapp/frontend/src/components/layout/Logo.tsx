import { motion } from "framer-motion";

export function Logo({ size = 64 }: { size?: number }) {
  return (
    <motion.div
      style={{ width: size, height: size }}
      className="relative grid place-items-center"
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.3 }}
    >
      <div className="absolute inset-0 rounded-full bg-accent/15 blur-2xl animate-breathe" />
      <svg
        viewBox="0 0 64 64"
        width={size}
        height={size}
        className="relative z-10 drop-shadow-[0_4px_12px_rgba(255,214,10,0.3)]"
      >
        <defs>
          <linearGradient id="lg" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0%" stopColor="#FFE066" />
            <stop offset="100%" stopColor="#FFD60A" />
          </linearGradient>
        </defs>
        <path
          d="M12 22 L20 14 L26 26 L32 12 L38 26 L44 14 L52 22 L48 48 L16 48 Z"
          fill="url(#lg)"
          stroke="#0E0E0F"
          strokeWidth="2"
          strokeLinejoin="round"
        />
        <circle cx="22" cy="40" r="2" fill="#0E0E0F" />
        <circle cx="32" cy="40" r="2" fill="#0E0E0F" />
        <circle cx="42" cy="40" r="2" fill="#0E0E0F" />
      </svg>
    </motion.div>
  );
}
