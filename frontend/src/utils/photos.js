import { uploadPhoto } from "@/lib/api";

// Regras de foto compartilhadas por anunciar, editar e relistar.
export const ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp"];
export const MIN_PHOTOS = Number(import.meta.env.VITE_MIN_PHOTOS || 3);
export const MAX_PHOTOS = Number(import.meta.env.VITE_MAX_PHOTOS || 10);
export const MAX_MB = Number(import.meta.env.VITE_MAX_PHOTO_MB || 5);
export const MAX_BYTES = MAX_MB * 1048576;

// Valida os arquivos e devolve os aceitos (com preview) + mensagens de erro.
// `remaining` limita ao espaço que ainda existe no leilão.
export function pickPhotos(list, remaining = MAX_PHOTOS) {
  const accepted = [];
  const errors = [];
  for (const file of Array.from(list || [])) {
    if (!ALLOWED_TYPES.includes(file.type)) {
      errors.push(`${file.name}: use JPG, PNG ou WebP.`);
      continue;
    }
    if (file.size > MAX_BYTES) {
      errors.push(`${file.name}: passa de ${MAX_MB} MB.`);
      continue;
    }
    if (accepted.length >= remaining) {
      errors.push(`Máximo de ${MAX_PHOTOS} fotos.`);
      break;
    }
    accepted.push({ file, url: URL.createObjectURL(file) });
  }
  return { accepted, errors };
}

// Sobe em paralelo e devolve as URLs públicas na mesma ordem.
export async function uploadPhotos(items, onProgress) {
  let done = 0;
  return Promise.all(
    items.map(async ({ file }) => {
      const url = await uploadPhoto(file);
      onProgress?.(++done, items.length);
      return url;
    })
  );
}
