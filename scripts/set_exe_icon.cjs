// set_exe_icon.cjs - electron-builder afterPack hook: puts the FLUX logo into FLUX.exe.
//
// signAndEditExecutable is off (electron-builder's rcedit comes from the winCodeSign
// download, which fails without a certificate / symlink rights), so the packaged exe kept
// Electron's icon: desktop shortcut, taskbar, Explorer (2026-09-26: only the
// installer had the FLUX logo). resedit (MIT, pure JS, already a dependency of
// electron-builder) replaces the exe's icon group with scripts/icon.ico.
'use strict'

const fs = require('fs')
const path = require('path')

function setExeIcon(exePath, icoPath) {
  const ResEdit = require('resedit')
  const exe = ResEdit.NtExecutable.from(fs.readFileSync(exePath), { ignoreCert: true })
  const res = ResEdit.NtExecutableResource.from(exe)
  const ico = ResEdit.Data.IconFile.from(fs.readFileSync(icoPath))
  // Replace the exe's own icon group (Electron's), else add one as id 1.
  const groups = ResEdit.Resource.IconGroupEntry.fromEntries(res.entries)
  const id = groups.length ? groups[0].id : 1
  const lang = groups.length ? groups[0].lang : 1033
  ResEdit.Resource.IconGroupEntry.replaceIconsForResource(res.entries, id, lang, ico.icons.map(i => i.data))
  res.outputResource(exe)
  fs.writeFileSync(exePath, Buffer.from(exe.generate()))
  return { id, lang, icons: ico.icons.length }
}

exports.setExeIcon = setExeIcon

exports.default = async function afterPack(context) {
  if (context.electronPlatformName !== 'win32') return
  const exe = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.exe`)
  const ico = path.join(__dirname, 'icon.ico')
  try {
    const r = setExeIcon(exe, ico)
    console.log(`[FLUX] exe icon set: ${path.basename(exe)} (group ${r.id}, ${r.icons} sizes)`)
  } catch (err) {
    // Never fail the build over the icon: the app works, only the exe keeps Electron's icon.
    console.warn(`[FLUX] exe icon not set (${err && err.message})`)
  }
}
