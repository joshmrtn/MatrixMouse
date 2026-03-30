#!/usr/bin/env node
// Build script for MatrixMouse frontend
// Bundles TypeScript into a single HTML file for the Python package

import { build } from 'esbuild';
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUTPUT_DIR = join(__dirname, '..', 'src', 'matrixmouse', 'web');

async function buildFrontend(): Promise<void> {
  console.log('Building MatrixMouse frontend...');
  
  // Ensure output directory exists
  if (!existsSync(OUTPUT_DIR)) {
    mkdirSync(OUTPUT_DIR, { recursive: true });
  }
  
  // Build JavaScript bundle
  const jsResult = await build({
    entryPoints: [join(__dirname, 'src', 'index.ts')],
    bundle: true,
    minify: true,
    sourcemap: false,
    target: 'es2020',
    format: 'iife',
    outfile: join(OUTPUT_DIR, 'ui.js'),
    write: false,
  });
  
  const jsContent = jsResult.outputFiles[0].text;
  
  // Read CSS
  const cssPath = join(OUTPUT_DIR, 'ui.css');
  let cssContent = '';
  if (existsSync(cssPath)) {
    cssContent = readFileSync(cssPath, 'utf-8');
  }
  
  // Read HTML template (original with markers)
  const htmlTemplatePath = join(__dirname, 'ui.template.html');
  let htmlContent = '';
  if (existsSync(htmlTemplatePath)) {
    htmlContent = readFileSync(htmlTemplatePath, 'utf-8');
  } else {
    // Fallback: read from output dir if template doesn't exist yet
    const htmlPath = join(OUTPUT_DIR, 'ui.html');
    if (existsSync(htmlPath)) {
      htmlContent = readFileSync(htmlPath, 'utf-8');
    }
  }
  
  if (!htmlContent) {
    console.error('Error: No HTML template found');
    process.exit(1);
  }
  
  // Inline CSS and JS into HTML
  let finalHtml = htmlContent
    .replace('<!-- CSS -->', cssContent)
    .replace('<!-- JS -->', jsContent);
  
  // Write final HTML
  const outputPath = join(OUTPUT_DIR, 'ui.html');
  writeFileSync(outputPath, finalHtml, 'utf-8');
  
  console.log(`✓ Build complete: ${outputPath}`);
  console.log(`  JavaScript: ${(jsContent.length / 1024).toFixed(1)} KB`);
  console.log(`  CSS: ${(cssContent.length / 1024).toFixed(1)} KB`);
  console.log(`  HTML: ${(finalHtml.length / 1024).toFixed(1)} KB`);
}

buildFrontend().catch(error => {
  console.error('Build failed:', error);
  process.exit(1);
});
