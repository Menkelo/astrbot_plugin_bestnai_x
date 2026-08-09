const ZIP_ENCODER = new TextEncoder();
let zipCrcTable = null;

export function safeZipName(value, fallback = "asset") {
  return String(value || fallback)
    .replace(/[\\/:*?"<>|\u0000-\u001f]+/g, "_")
    .replace(/^\.+|\.+$/g, "")
    .trim()
    .slice(0, 72) || fallback;
}

export function decodeDataUrl(dataUrl) {
  const match = /^data:([^;,]+)(;base64)?,(.*)$/s.exec(String(dataUrl || ""));
  if (!match) throw new Error("图片素材数据无效");
  const mimeType = match[1].toLowerCase();
  if (match[2]) {
    const binary = atob(match[3]);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    return { mimeType, bytes };
  }
  return { mimeType, bytes: ZIP_ENCODER.encode(decodeURIComponent(match[3])) };
}

export function imageExtension(mimeType) {
  return ({
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
  })[String(mimeType || "").toLowerCase()] || "bin";
}

export function uniqueZipPath(folder, basename, extension, usedPaths) {
  const safeFolder = safeZipName(folder, "素材");
  const safeBase = safeZipName(basename, "asset");
  const safeExtension = String(extension || "bin").replace(/[^a-z0-9]/gi, "").toLowerCase() || "bin";
  let candidate = `${safeFolder}/${safeBase}.${safeExtension}`;
  let suffix = 2;
  while (usedPaths.has(candidate)) {
    candidate = `${safeFolder}/${safeBase}-${suffix}.${safeExtension}`;
    suffix += 1;
  }
  usedPaths.add(candidate);
  return candidate;
}

function zipCrc32(bytes) {
  if (!zipCrcTable) {
    zipCrcTable = new Uint32Array(256);
    for (let index = 0; index < 256; index += 1) {
      let checksum = index;
      for (let bit = 0; bit < 8; bit += 1) {
        checksum = (checksum & 1) ? (0xedb88320 ^ (checksum >>> 1)) : (checksum >>> 1);
      }
      zipCrcTable[index] = checksum >>> 0;
    }
  }
  let crc = 0xffffffff;
  for (let index = 0; index < bytes.length; index += 1) {
    crc = zipCrcTable[(crc ^ bytes[index]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function zipDosTime(date = new Date()) {
  const time = (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2);
  const year = Math.max(1980, date.getFullYear());
  const day = ((year - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
  return { time, day };
}

function zipHeader(signature, size) {
  const bytes = new Uint8Array(size);
  const view = new DataView(bytes.buffer);
  view.setUint32(0, signature, true);
  return { bytes, view };
}

export function createZipBlob(entries) {
  const now = zipDosTime();
  const files = [];
  const central = [];
  let offset = 0;
  entries.forEach((entry) => {
    const nameBytes = ZIP_ENCODER.encode(entry.name);
    const data = entry.bytes instanceof Uint8Array
      ? entry.bytes
      : ZIP_ENCODER.encode(String(entry.bytes || ""));
    const crc = zipCrc32(data);
    const local = zipHeader(0x04034b50, 30 + nameBytes.length);
    local.view.setUint16(4, 20, true);
    local.view.setUint16(6, 0x0800, true);
    local.view.setUint16(8, 0, true);
    local.view.setUint16(10, now.time, true);
    local.view.setUint16(12, now.day, true);
    local.view.setUint32(14, crc, true);
    local.view.setUint32(18, data.length, true);
    local.view.setUint32(22, data.length, true);
    local.view.setUint16(26, nameBytes.length, true);
    local.bytes.set(nameBytes, 30);
    files.push(local.bytes, data);

    const directory = zipHeader(0x02014b50, 46 + nameBytes.length);
    directory.view.setUint16(4, 20, true);
    directory.view.setUint16(6, 20, true);
    directory.view.setUint16(8, 0x0800, true);
    directory.view.setUint16(10, 0, true);
    directory.view.setUint16(12, now.time, true);
    directory.view.setUint16(14, now.day, true);
    directory.view.setUint32(16, crc, true);
    directory.view.setUint32(20, data.length, true);
    directory.view.setUint32(24, data.length, true);
    directory.view.setUint16(28, nameBytes.length, true);
    directory.view.setUint32(42, offset, true);
    directory.bytes.set(nameBytes, 46);
    central.push(directory.bytes);
    offset += local.bytes.length + data.length;
  });

  const centralSize = central.reduce((sum, bytes) => sum + bytes.length, 0);
  const end = zipHeader(0x06054b50, 22);
  end.view.setUint16(8, entries.length, true);
  end.view.setUint16(10, entries.length, true);
  end.view.setUint32(12, centralSize, true);
  end.view.setUint32(16, offset, true);
  return new Blob([...files, ...central, end.bytes], { type: "application/zip" });
}

export function downloadBlob(blob, filename) {
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(href), 1500);
}

export function encodeZipText(value) {
  return ZIP_ENCODER.encode(String(value || ""));
}
