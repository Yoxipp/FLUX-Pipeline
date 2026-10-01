; installer.nsh — hooks NSIS custom pour l'installeur FLUX (electron-builder).
; Objectif : detecter une version deja installee sur la machine et afficher un
; message clair "mise a jour" vs "installation neuve" avant de continuer.
;
; Macros disponibles (electron-builder) : customHeader, preInit, customInit,
; customInstall, customInstallMode, customWelcomePage, customFinishPage, etc.
; Doc : https://www.electron.build/configuration/nsis
;
; Registre (per-user, perMachine:false => SHELL_CONTEXT = HKCU) :
;   ${UNINSTALL_REGISTRY_KEY}\DisplayVersion  = version actuellement installee
;   ${UNINSTALL_REGISTRY_KEY}\FluxVersion     = version affichee installee (x.x.xxx)
;   ${VERSION}                                = version semver en cours d'installation
;   ${FLUX_VERSION}                           = version affichee (x.x.xxx), flux_version.nsh

; Genere par scripts/build.cjs a chaque build.
!include "${BUILD_RESOURCES_DIR}\flux_version.nsh"

; --- customInit -------------------------------------------------------------
; Insere dans .onInit APRES initMultiUser : SHELL_CONTEXT et la detection
; d'install existante sont deja resolus a ce point.
!macro customInit
  ; En mode silencieux (/S), on ne bloque jamais avec une boite de dialogue.
  ${ifNot} ${Silent}
    ReadRegStr $R6 SHELL_CONTEXT "${UNINSTALL_REGISTRY_KEY}" "DisplayVersion"
    ; Libelle affiche : FluxVersion si present (builds x.x.xxx), sinon DisplayVersion.
    ReadRegStr $R7 SHELL_CONTEXT "${UNINSTALL_REGISTRY_KEY}" "FluxVersion"
    ${if} $R7 == ""
      StrCpy $R7 $R6
    ${endif}

    ${if} $R6 != ""
      ; Une version de FLUX est deja presente sur la machine.
      ${if} $R6 == "${VERSION}"
        ; Meme version => reinstallation / reparation.
        MessageBox MB_OKCANCEL|MB_ICONINFORMATION \
          "FLUX ${FLUX_VERSION} est deja installe sur cette machine.$\r$\n$\r$\nContinuer va reinstaller (reparer) cette version.$\r$\n$\r$\nVos preferences et projets ne sont pas touches." \
          IDOK flux_continue
        Quit
      ${else}
        ; Version differente => mise a jour.
        MessageBox MB_OKCANCEL|MB_ICONINFORMATION \
          "Une version de FLUX est deja installee : $R7$\r$\n$\r$\nElle va etre mise a jour vers la version ${FLUX_VERSION}.$\r$\n$\r$\nVos preferences et projets ne sont pas touches." \
          IDOK flux_continue
        Quit
      ${endif}
      flux_continue:
    ${endif}
  ${endif}
!macroend

; --- customInstall ----------------------------------------------------------
; Memorise la version affichee (x.x.xxx) pour le message de la prochaine MAJ.
!macro customInstall
  WriteRegStr SHELL_CONTEXT "${UNINSTALL_REGISTRY_KEY}" "FluxVersion" "${FLUX_VERSION}"
!macroend

; --- customUnInstall --------------------------------------------------------
; "Uninstall FLUX.exe" (next to FLUX.exe, also launched by Settings > Desinstaller FLUX)
; removes everything FLUX added to this machine, not only the app files:
;   1. flux_backend.exe --uninstall-cleanup : FLUX blocks / bridges / plugins / HDAs /
;      shelves / $FLUX package / ZBrush PYTHONPATH entry in the DCCs
;      (backend/features/system/uninstall.py). Python and its packages, the DCCs,
;      the projects and the user's own startup code are never touched.
;   2. the per-user data dirs FLUX writes (config, prefs, logs, staged HDAs).
; Skipped on an update: the old version is uninstalled before the new one is
; installed, and the DCCs / preferences must survive that.
; Runs before electron-builder deletes $INSTDIR, so the backend exe still exists.
!macro customUnInstall
  ${ifNot} ${isUpdated}
    ; A backend left running would keep files of $INSTDIR locked.
    nsExec::Exec 'taskkill /F /T /IM flux_backend.exe'
    Pop $0
    IfFileExists "$INSTDIR\resources\backend\flux_backend.exe" 0 flux_no_backend
      DetailPrint "FLUX : nettoyage des logiciels (Maya, Houdini, Nuke...)"
      nsExec::ExecToLog '"$INSTDIR\resources\backend\flux_backend.exe" --uninstall-cleanup'
      Pop $0
    flux_no_backend:
    ; Per-user data: electron always uses the current user's app data.
    ${if} $installMode == "all"
      SetShellVarContext current
    ${endif}
    RMDir /r "$APPDATA\FLUX"
    RMDir /r "$APPDATA\FluxPipeline"
    RMDir /r "$LOCALAPPDATA\FLUX"
    RMDir /r "$APPDATA\flux-pipeline"
    ${if} $installMode == "all"
      SetShellVarContext all
    ${endif}
  ${endif}
!macroend
