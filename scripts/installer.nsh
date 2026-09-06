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
;   ${VERSION}                                = version en cours d'installation

; --- customInit -------------------------------------------------------------
; Insere dans .onInit APRES initMultiUser : SHELL_CONTEXT et la detection
; d'install existante sont deja resolus a ce point.
!macro customInit
  ; En mode silencieux (/S), on ne bloque jamais avec une boite de dialogue.
  ${ifNot} ${Silent}
    ReadRegStr $R6 SHELL_CONTEXT "${UNINSTALL_REGISTRY_KEY}" "DisplayVersion"

    ${if} $R6 != ""
      ; Une version de FLUX est deja presente sur la machine.
      ${if} $R6 == "${VERSION}"
        ; Meme version => reinstallation / reparation.
        MessageBox MB_OKCANCEL|MB_ICONINFORMATION \
          "FLUX ${VERSION} est deja installe sur cette machine.$\r$\n$\r$\nContinuer va reinstaller (reparer) cette version.$\r$\n$\r$\nVos preferences et projets ne sont pas touches." \
          IDOK flux_continue
        Quit
      ${else}
        ; Version differente => mise a jour.
        MessageBox MB_OKCANCEL|MB_ICONINFORMATION \
          "Une version de FLUX est deja installee : $R6$\r$\n$\r$\nElle va etre mise a jour vers la version ${VERSION}.$\r$\n$\r$\nVos preferences et projets ne sont pas touches." \
          IDOK flux_continue
        Quit
      ${endif}
      flux_continue:
    ${endif}
  ${endif}
!macroend
