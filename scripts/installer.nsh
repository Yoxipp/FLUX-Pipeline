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
