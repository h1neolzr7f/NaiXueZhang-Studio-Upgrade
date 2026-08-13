export type ImageAttachment = {
  name: string;
  mime: string;
  size_bytes: number;
  data_url: string;
};

const SUPPORTED = new Set(["image/png", "image/jpeg", "image/webp"]);

function readDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result || "")), { once: true });
    reader.addEventListener("error", () => reject(new Error("图片读取失败")), { once: true });
    reader.readAsDataURL(blob);
  });
}

function canvasBlob(canvas: HTMLCanvasElement, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("图片压缩失败"))), "image/jpeg", quality);
  });
}

async function loadBitmap(file: File): Promise<ImageBitmap | HTMLImageElement> {
  if (typeof window.createImageBitmap === "function") return window.createImageBitmap(file);
  return new Promise((resolve, reject) => {
    const image = new Image();
    const url = URL.createObjectURL(file);
    image.addEventListener(
      "load",
      () => {
        URL.revokeObjectURL(url);
        resolve(image);
      },
      { once: true },
    );
    image.addEventListener(
      "error",
      () => {
        URL.revokeObjectURL(url);
        reject(new Error("图片无法解码"));
      },
      { once: true },
    );
    image.src = url;
  });
}

export async function compressImage(file: File): Promise<ImageAttachment> {
  if (!file || !SUPPORTED.has(file.type)) throw new Error("请选择 PNG、JPEG 或 WebP 图片");
  if (file.size > 20 * 1024 * 1024) throw new Error("原图超过 20MB，请先缩小后再试");
  const bitmap = await loadBitmap(file);
  const sourceWidth = Number("width" in bitmap ? bitmap.width : 0);
  const sourceHeight = Number("height" in bitmap ? bitmap.height : 0);
  if (!sourceWidth || !sourceHeight) throw new Error("图片尺寸读取失败");
  const ratio = Math.min(1, 1536 / Math.max(sourceWidth, sourceHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(sourceWidth * ratio));
  canvas.height = Math.max(1, Math.round(sourceHeight * ratio));
  const context = canvas.getContext("2d", { alpha: false });
  if (!context) throw new Error("无法压缩图片");
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  if ("close" in bitmap && typeof bitmap.close === "function") bitmap.close();
  let blob = await canvasBlob(canvas, 0.84);
  if (blob.size > 6 * 1024 * 1024) blob = await canvasBlob(canvas, 0.68);
  if (blob.size > 6 * 1024 * 1024) throw new Error("压缩后仍超过 6MB，请换一张更小的图片");
  return {
    name: String(file.name || "图片").slice(0, 120),
    mime: "image/jpeg",
    size_bytes: blob.size,
    data_url: await readDataUrl(blob),
  };
}
