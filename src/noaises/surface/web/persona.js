/**
 * Persona animation state machine — Lottie blob + particle effects.
 * States: idle, listening, thinking, searching, speaking, sleeping, seeing, remembering
 * Called from Python via pywebview's evaluate_js bridge.
 */

const STATES = ["idle", "listening", "thinking", "searching", "speaking", "sleeping", "seeing", "remembering"];
let currentState = "idle";
let particleInterval = null;
let lottieAnim = null;

// CSS-drawn particle configuration per state
const PARTICLE_CONFIG = {
  thinking: {
    interval: 600,
    shapes: ["sparkle-star", "glow-dot", "glow-dot"],
  },
  searching: {
    interval: 500,
    shapes: ["page-icon", "glow-dot", "page-icon", "glow-dot"],
  },
  seeing: {
    interval: 450,
    shapes: ["iris-ring", "light-ray", "glow-dot", "iris-ring"],
  },
  remembering: {
    interval: 700,
    shapes: ["cloud-puff", "sparkle-star", "glow-dot", "cloud-puff"],
  },
};

// Lottie speed per state (base animation is 5fps idle loop)
const STATE_SPEED = {
  idle: 1,
  listening: 1.3,
  thinking: 0.7,
  searching: 1.5,
  speaking: 1.2,
  sleeping: 0.3,
  seeing: 1.4,
  remembering: 0.6,
};

/**
 * Create a CSS-drawn particle element for the given shape kind.
 * @param {string} shape - One of: sparkle-star, glow-dot, iris-ring, light-ray, cloud-puff, page-icon
 * @returns {HTMLElement}
 */
function createShapedParticle(shape) {
  const el = document.createElement("div");
  el.className = "particle--shape";

  const size = 8 + Math.random() * 6;

  switch (shape) {
    case "sparkle-star": {
      el.style.width = `${size}px`;
      el.style.height = `${size}px`;
      el.style.background = "#fdcb6e";
      el.style.clipPath = "polygon(50% 0%, 61% 35%, 98% 35%, 68% 57%, 79% 91%, 50% 70%, 21% 91%, 32% 57%, 2% 35%, 39% 35%)";
      el.style.filter = `drop-shadow(0 0 3px rgba(253, 203, 110, 0.8))`;
      break;
    }
    case "glow-dot": {
      const dotSize = 4 + Math.random() * 4;
      el.style.width = `${dotSize}px`;
      el.style.height = `${dotSize}px`;
      el.style.borderRadius = "50%";
      el.style.background = "rgba(255, 255, 255, 0.8)";
      el.style.boxShadow = "0 0 6px rgba(255, 255, 255, 0.6), 0 0 12px rgba(162, 155, 254, 0.3)";
      break;
    }
    case "iris-ring": {
      const ringSize = 10 + Math.random() * 6;
      el.style.width = `${ringSize}px`;
      el.style.height = `${ringSize}px`;
      el.style.borderRadius = "50%";
      el.style.background = "transparent";
      el.style.border = "1.5px solid rgba(0, 184, 148, 0.7)";
      el.style.boxShadow = "inset 0 0 4px rgba(0, 184, 148, 0.3)";
      break;
    }
    case "light-ray": {
      el.style.width = "2px";
      el.style.height = `${14 + Math.random() * 10}px`;
      el.style.background = "linear-gradient(to bottom, rgba(0, 184, 148, 0.6), transparent)";
      el.style.borderRadius = "1px";
      break;
    }
    case "cloud-puff": {
      const puffSize = 10 + Math.random() * 8;
      el.style.width = `${puffSize}px`;
      el.style.height = `${puffSize * 0.65}px`;
      el.style.borderRadius = "50%";
      el.style.background = "rgba(162, 155, 254, 0.35)";
      el.style.boxShadow = `${puffSize * 0.4}px 2px 0 rgba(162, 155, 254, 0.25), ${-puffSize * 0.3}px 1px 0 rgba(162, 155, 254, 0.2)`;
      el.style.filter = "blur(1px)";
      break;
    }
    case "page-icon": {
      el.style.width = `${size * 0.8}px`;
      el.style.height = `${size}px`;
      el.style.background = "rgba(116, 185, 255, 0.6)";
      el.style.clipPath = "polygon(0 0, 70% 0, 100% 25%, 100% 100%, 0 100%)";
      el.style.borderRadius = "1px";
      break;
    }
  }

  return el;
}

/**
 * Set the persona's animation state.
 * @param {string} state - One of: idle, listening, thinking, searching, speaking, sleeping, seeing, remembering
 */
function setPersonaState(state) {
  if (!STATES.includes(state)) return;

  const el = document.getElementById("persona");
  if (!el) return;

  // Remove all state classes
  STATES.forEach((s) => el.classList.remove(`persona--${s}`));

  // Stop any running particle spawner
  stopParticles();

  // Apply new state
  el.classList.add(`persona--${state}`);
  currentState = state;

  // Update Lottie playback speed
  if (lottieAnim) {
    lottieAnim.setSpeed(STATE_SPEED[state] || 1);

    if (state === "sleeping") {
      lottieAnim.setDirection(-1);
    } else {
      lottieAnim.setDirection(1);
    }
  }

  // Start particles for states that have config
  if (PARTICLE_CONFIG[state]) {
    startParticles(state);
  }
}

/**
 * Spawn a single CSS-drawn floating particle.
 */
function spawnParticle(state) {
  const container = document.getElementById("particles");
  if (!container) return;

  const config = PARTICLE_CONFIG[state];
  if (!config) return;

  const shape = config.shapes[Math.floor(Math.random() * config.shapes.length)];
  const particle = createShapedParticle(shape);

  // Random position around the blob
  const angle = Math.random() * Math.PI * 2;
  const radius = 60 + Math.random() * 30;
  const startX = Math.cos(angle) * radius;
  const startY = Math.sin(angle) * radius - 20;

  // Random drift direction
  const driftX = (Math.random() - 0.5) * 60;
  const driftY = -(40 + Math.random() * 50); // always float upward

  particle.style.setProperty("--start-x", `${startX}px`);
  particle.style.setProperty("--start-y", `${startY}px`);
  particle.style.setProperty("--drift-x", `${driftX}px`);
  particle.style.setProperty("--drift-y", `${driftY}px`);
  particle.style.setProperty("--rotate", `${(Math.random() - 0.5) * 40}deg`);

  container.appendChild(particle);

  // Remove after animation ends
  particle.addEventListener("animationend", () => particle.remove());
}

function startParticles(state) {
  const config = PARTICLE_CONFIG[state];
  if (!config) return;
  // Spawn one immediately, then on interval
  spawnParticle(state);
  particleInterval = setInterval(() => spawnParticle(state), config.interval);
}

function stopParticles() {
  if (particleInterval) {
    clearInterval(particleInterval);
    particleInterval = null;
  }
  const container = document.getElementById("particles");
  if (container) {
    container.innerHTML = "";
  }
}

// Initialize Lottie and start in idle state
document.addEventListener("DOMContentLoaded", () => {
  lottieAnim = lottie.loadAnimation({
    container: document.getElementById("lottieWrap"),
    renderer: "svg",
    loop: true,
    autoplay: true,
    path: "blob-anim.json",
  });

  setPersonaState("idle");
});
