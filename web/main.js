// Point d'entrée: la ville en 3D si le navigateur le permet, sinon une image fixe + le tableau de bord.
import { fallback, startHud } from "./hud.js";

function webglAvailable() {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

async function boot() {
  if (!webglAvailable()) {
    fallback("Your browser can't show 3D here. This is a still picture of the town.");
    startHud();
    return;
  }
  try {
    const city = await import("./city3d.js?v=3");
    city.start();
  } catch (err) {
    console.error(err);
    fallback("The 3D town could not start in this browser. This is a still picture of it.");
    startHud();
  }
}
boot();
