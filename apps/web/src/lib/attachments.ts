/** Pièces justificatives : formats acceptés et réduction des photos avant envoi (3G). */

export const ACCEPTED_TYPES = ["application/pdf", "image/jpeg", "image/png", "image/webp"] as const;
/** Attribut `accept` du champ fichier : les photos HEIC des iPhone sont converties par le navigateur. */
export const ACCEPT_ATTRIBUTE = [...ACCEPTED_TYPES, ".pdf", ".jpg", ".jpeg", ".png", ".webp"].join(",");
export const MAX_BYTES = 10 * 1024 * 1024;

/** Côté le plus long d'une photo envoyée : reste lisible pour une facture ou un reçu. */
export const MAX_IMAGE_SIDE = 2000;
const JPEG_QUALITY = 0.82;
/** En dessous, une image est envoyée telle quelle. */
const SHRINK_THRESHOLD_BYTES = 600 * 1024;

export function fitWithin(width: number, height: number, maxSide: number): { width: number; height: number } {
  const longest = Math.max(width, height);
  if (longest <= maxSide) return { width, height };
  const scale = maxSide / longest;
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

export function shouldShrink(file: { type: string; size: number }): boolean {
  return file.type.startsWith("image/") && file.size > SHRINK_THRESHOLD_BYTES;
}

/** Nom du fichier réduit : même nom, extension .jpg. */
export function shrunkName(name: string): string {
  const base = name.replace(/\.[^./\\]+$/, "") || "photo";
  return `${base}.jpg`;
}

export function formatSize(bytes: number, locale: string): string {
  const units = locale === "en" ? ["B", "KB", "MB"] : ["o", "Ko", "Mo"];
  if (bytes < 1024) return `${bytes} ${units[0]}`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${Math.round(kb).toLocaleString(locale)} ${units[1]}`;
  return `${(kb / 1024).toLocaleString(locale, { maximumFractionDigits: 1 })} ${units[2]}`;
}

/**
 * Réduit une photo (dimensions et poids) dans le navigateur avant l'envoi : une photo
 * de téléphone de 4 Mo devient ~300 Ko. En cas d'échec (format non décodable), le
 * fichier d'origine est envoyé et le serveur décide.
 */
export async function shrinkImage(file: File): Promise<File> {
  if (!shouldShrink(file)) return file;
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const { width, height } = fitWithin(bitmap.width, bitmap.height, MAX_IMAGE_SIDE);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (!context) return file;
    // Fond blanc : la transparence d'un PNG deviendrait noire en JPEG.
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, width, height);
    context.drawImage(bitmap, 0, 0, width, height);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY));
    if (!blob || blob.size >= file.size) return file;
    return new File([blob], shrunkName(file.name), { type: "image/jpeg", lastModified: file.lastModified });
  } catch {
    return file;
  }
}
