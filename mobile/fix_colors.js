const fs = require('fs');
const path = require('path');

const directoryPath = path.join(__dirname, 'src');

const replacements = {
  '#f1f3f5': '#f4efe6',
  '#212529': '#1f2933',
  '#6c757d': '#5b6773',
  '#4361ee': '#145374',
  '#eef2ff': '#e6ecef',
  '#d1dbff': '#c3d6e0',
  '#dee2e6': '#e0d8d0',
  '#e63946': '#a43f24',
  '#2a9d8f': '#1f7a58',
  '#4cc9f0': '#0d3c52',
  '#f8f9fa': '#fcf9f3',
};

function processDirectory(dir) {
  const files = fs.readdirSync(dir);
  for (const file of files) {
    const fullPath = path.join(dir, file);
    if (fs.statSync(fullPath).isDirectory()) {
      processDirectory(fullPath);
    } else if (fullPath.endsWith('.tsx') || fullPath.endsWith('.ts')) {
      let content = fs.readFileSync(fullPath, 'utf8');
      let newContent = content;
      for (const [oldColor, newColor] of Object.entries(replacements)) {
        newContent = newContent.split(oldColor).join(newColor);
      }
      if (content !== newContent) {
        fs.writeFileSync(fullPath, newContent, 'utf8');
        console.log(`Updated ${fullPath}`);
      }
    }
  }
}

processDirectory(directoryPath);

// Update tailwind config
let twContent = fs.readFileSync('tailwind.config.js', 'utf8');
for (const [oldColor, newColor] of Object.entries(replacements)) {
  twContent = twContent.split(oldColor).join(newColor);
}
fs.writeFileSync('tailwind.config.js', twContent, 'utf8');
console.log('Updated tailwind.config.js');
