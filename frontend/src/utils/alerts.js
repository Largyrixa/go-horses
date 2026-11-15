import Swal from "sweetalert2";

const dark = { background: "#14141B", color: "#F2F0E8" };

// `titleText` (e não `title`): o SweetAlert2 interpreta `title` como HTML, e aqui entram textos
// vindos do servidor e nomes digitados por usuários.
export const toast = (icon, title) =>
  Swal.mixin({ toast: true, position: "top-end", showConfirmButton: false, timer: 4000, timerProgressBar: true, ...dark }).fire({ icon, titleText: String(title ?? "") });

export async function confirmDanger({ title, text, confirmText }) {
  const r = await Swal.fire({
    ...dark, titleText: String(title ?? ""), text, icon: "warning", showCancelButton: true, reverseButtons: true,
    confirmButtonText: confirmText, cancelButtonText: "Voltar", confirmButtonColor: "#FF4D5E", cancelButtonColor: "#2A2A36",
  });
  return r.isConfirmed;
}
