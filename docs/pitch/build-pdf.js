// Gera docs/pitch/roteiro-pitch.pdf a partir de roteiro-pitch.html.
//
// Requer o pacote `playwright-core` e um Chromium do Playwright:
//   npm i playwright-core
//   node docs/pitch/build-pdf.js
//
// Se o Chromium estiver em outro lugar, defina CHROME_PATH.
const { chromium } = require("playwright-core");
const path = require("path");
const fs = require("fs");

function findChrome() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const base = path.join(process.env.HOME || "", ".cache/ms-playwright");
  if (fs.existsSync(base)) {
    for (const dir of fs.readdirSync(base)) {
      if (dir.startsWith("chromium-")) {
        const p = path.join(base, dir, "chrome-linux64", "chrome");
        if (fs.existsSync(p)) return p;
      }
    }
  }
  throw new Error("Chromium do Playwright não encontrado; defina CHROME_PATH.");
}

(async () => {
  const root = __dirname;
  const browser = await chromium.launch({ executablePath: findChrome() });
  const page = await browser.newPage();
  await page.goto("file://" + path.join(root, "roteiro-pitch.html"), { waitUntil: "networkidle" });
  await page.pdf({
    path: path.join(root, "roteiro-pitch.pdf"),
    format: "A4",
    printBackground: true,
    margin: { top: "16mm", right: "15mm", bottom: "18mm", left: "15mm" },
    displayHeaderFooter: true,
    headerTemplate: "<div></div>",
    footerTemplate:
      '<div style="width:100%;font-size:7.5pt;color:#6b7280;padding:0 15mm;display:flex;justify-content:space-between;">' +
      '<span>Go Horses · Roteiro de Pitch</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>',
  });
  await browser.close();
  console.log("PDF gerado em", path.join(root, "roteiro-pitch.pdf"));
})();
