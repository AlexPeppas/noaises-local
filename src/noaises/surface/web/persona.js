/**
 * Persona animation state machine with particle effects.
 * States: idle, listening, thinking, searching, speaking
 * Called from Python via pywebview's evaluate_js bridge.
 */

const STATES = ["idle", "listening", "thinking", "searching", "speaking", "sleeping"];
let currentState = "idle";
let particleInterval = null;

// Emoji pools per state
const PARTICLE_SETS = {
  thinking: ["\u{1F4A1}", "\u{2728}", "\u{1F4A1}", "\u{2728}", "\u{1F31F}", "\u{1F4A1}"],
  searching: ["\u{1F4D6}", "\u{1F4DA}", "\u{1F50D}", "\u{1F4C4}", "\u{1F4DD}", "\u{1F310}", "\u{1F516}", "\u{1F50E}"],
};

/**
 * Set the persona's animation state.
 * @param {string} state - One of: idle, listening, thinking, searching, speaking
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

  // Start particles for states that need them
  if (PARTICLE_SETS[state]) {
    startParticles(state);
  }
}

/**
 * Spawn a single floating particle emoji.
 */
function spawnParticle(state) {
  const container = document.getElementById("particles");
  if (!container) return;

  const emojis = PARTICLE_SETS[state];
  if (!emojis) return;

  const particle = document.createElement("span");
  particle.className = "particle";
  particle.textContent = emojis[Math.floor(Math.random() * emojis.length)];

  // Random position around the blob
  const angle = Math.random() * Math.PI * 2;
  const radius = 50 + Math.random() * 30;
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
  particle.style.fontSize = `${14 + Math.random() * 10}px`;

  container.appendChild(particle);

  // Remove after animation ends
  particle.addEventListener("animationend", () => particle.remove());
}

function startParticles(state) {
  // Spawn one immediately, then on interval
  spawnParticle(state);
  particleInterval = setInterval(() => spawnParticle(state), 600);
}

function stopParticles() {
  if (particleInterval) {
    clearInterval(particleInterval);
    particleInterval = null;
  }
  // Clear remaining particles (they'll fade out via animation)
  const container = document.getElementById("particles");
  if (container) {
    container.innerHTML = "";
  }
}

// Start in idle state
document.addEventListener("DOMContentLoaded", () => {
  setPersonaState("idle");

  // Click-to-interrupt: clicking persona during thinking/speaking fires interrupt
  document.getElementById("persona").addEventListener("click", () => {
    if (currentState === "thinking" || currentState === "speaking") {
      window.pywebview.api.on_persona_clicked();
    }
  });
});
