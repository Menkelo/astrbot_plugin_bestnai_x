// The editor and outgoing request must use the same precedence and bounds.
export const ADV_RANGES = {
  steps: { min: 1, max: 28 },
  scale: { min: 1, max: 10 },
  cfgRescale: { min: 0, max: 1 },
};

export function hasParameterValue(key, value) {
  if (value == null || value === "" || typeof value === "boolean") return false;
  const bounds = ADV_RANGES[key];
  if (!bounds) return typeof value === "string" && !!value.trim();
  const number = Number(value);
  return Number.isFinite(number) && number >= bounds.min;
}

export function effectiveParameter(meta, key, sourceKey, fallback) {
  const value = [meta?.[key], meta?.[sourceKey], fallback].find((item) => hasParameterValue(key, item));
  if (value === undefined) return undefined;
  const bounds = ADV_RANGES[key];
  if (!bounds) return value.trim();
  const number = Math.min(bounds.max, Math.max(bounds.min, Number(value)));
  return key === "steps" ? Math.round(number) : number;
}

export function generationParameterPayload(meta = {}) {
  const imageFormat = String(meta.imageFormat || "").toLowerCase().replace(/^jpeg$/, "jpg");
  return {
    steps: effectiveParameter(meta, "steps", "retagSteps"),
    scale: effectiveParameter(meta, "scale", "retagScale"),
    cfg_rescale: effectiveParameter(meta, "cfgRescale", "retagCfgRescale"),
    sampler: effectiveParameter(meta, "sampler", "retagSampler"),
    noise_schedule: effectiveParameter(meta, "noiseSchedule", "retagNoiseSchedule"),
    negative_prompt: meta.negativePrompt,
    uc_preset: meta.ucPreset,
    image_format: ["png", "jpg", "webp"].includes(imageFormat) ? imageFormat : undefined,
    quality: meta.quality,
  };
}
