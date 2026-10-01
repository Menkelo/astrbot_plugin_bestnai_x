// The editor and outgoing request must use the same precedence and bounds.
export const ADV_RANGES = {
  steps: { min: 1, max: 28 },
  scale: { min: 1, max: 10 },
  cfgRescale: { min: 0, max: 1 },
};

// 步数上限随模型走，与后端 models/config.py 的 MODEL_STEP_LIMITS 一一对应：
// V5（nai-diffusion-5-full）锁 23，V4.5 保持 28。滑条、反推带回的原图参数、
// 缓存复用三处都必须用这个函数取上限，否则会出现滑条卡 28、实际发 23 的错位。
export const MODEL_STEP_LIMITS = {
  "nai-diffusion-5-full": 23,
  "nai-diffusion-4-5-full": 28,
};
export const DEFAULT_STEP_LIMIT = ADV_RANGES.steps.max;

export function stepLimitForModel(model) {
  const key = String(model || "").trim().toLowerCase();
  return MODEL_STEP_LIMITS[key] ?? DEFAULT_STEP_LIMIT;
}

// 按模型返回一份钳制后的 steps 取值范围，其余键原样沿用 ADV_RANGES。
export function rangesForModel(model) {
  return { ...ADV_RANGES, steps: { ...ADV_RANGES.steps, max: stepLimitForModel(model) } };
}

export function hasParameterValue(key, value, ranges = ADV_RANGES) {
  if (value == null || value === "" || typeof value === "boolean") return false;
  const bounds = ranges[key];
  if (!bounds) return typeof value === "string" && !!value.trim();
  const number = Number(value);
  return Number.isFinite(number) && number >= bounds.min;
}

export function effectiveParameter(meta, key, sourceKey, fallback, ranges = ADV_RANGES) {
  const value = [meta?.[key], meta?.[sourceKey], fallback].find((item) => hasParameterValue(key, item, ranges));
  if (value === undefined) return undefined;
  const bounds = ranges[key];
  if (!bounds) return value.trim();
  const number = Math.min(bounds.max, Math.max(bounds.min, Number(value)));
  return key === "steps" ? Math.round(number) : number;
}

export function generationParameterPayload(meta = {}, model = "") {
  const ranges = rangesForModel(model);
  const imageFormat = String(meta.imageFormat || "").toLowerCase().replace(/^jpeg$/, "jpg");
  return {
    steps: effectiveParameter(meta, "steps", "retagSteps", undefined, ranges),
    scale: effectiveParameter(meta, "scale", "retagScale", undefined, ranges),
    cfg_rescale: effectiveParameter(meta, "cfgRescale", "retagCfgRescale", undefined, ranges),
    sampler: effectiveParameter(meta, "sampler", "retagSampler", undefined, ranges),
    noise_schedule: effectiveParameter(meta, "noiseSchedule", "retagNoiseSchedule", undefined, ranges),
    negative_prompt: meta.negativePrompt,
    uc_preset: meta.ucPreset,
    image_format: ["png", "jpg", "webp"].includes(imageFormat) ? imageFormat : undefined,
    quality: meta.quality,
  };
}
