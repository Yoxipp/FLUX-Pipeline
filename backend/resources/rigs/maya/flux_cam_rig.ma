//Maya ASCII 2024 scene
//Name: flux_cam_rig.ma
//Last modified: Sat, Sep 26, 2026 11:28:44 PM
//Codeset: 1252
requires maya "2024";
currentUnit -l centimeter -a degree -t film;
fileInfo "application" "maya";
fileInfo "product" "Maya 2024";
fileInfo "version" "2024";
fileInfo "cutIdentifier" "202310181224-69282f2959";
fileInfo "osv" "Windows 11 Pro v2009 (Build: 26200)";
fileInfo "UUID" "8FDBBBA0-4E74-36ED-AD0A-909EC885450B";
createNode transform -n "Flux_Cam_Rig";
	rename -uid "941B73D7-447B-5930-54B4-5D81881BBCDC";
	addAttr -ci true -sn "flux_rig" -ln "flux_rig" -dt "string";
	setAttr ".flux_rig" -type "string" "camera";
createNode transform -n "Cam" -p "Flux_Cam_Rig";
	rename -uid "C13A09C0-4278-095C-E755-1A8C61C762C2";
	addAttr -ci true -sn "artMtxCon" -ln "artMtxCon" -dt "string";
	setAttr -l on ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 14;
	setAttr -l on ".tx";
	setAttr -l on ".ty";
	setAttr -l on ".tz";
	setAttr -l on ".sx";
	setAttr -l on ".sy";
	setAttr -l on ".sz";
	setAttr ".artMtxCon" -type "string" "parent|offsetParentMatrix|Ctrl_Adjust_Cam";
createNode camera -n "CamShape" -p "Cam";
	rename -uid "037FD633-4A24-0661-5D20-6DA9677BD228";
	setAttr -k off ".v";
	setAttr ".ovp" no;
	setAttr ".ove" yes;
	setAttr ".ovrgbf" yes;
	setAttr ".ovc" 14;
	setAttr ".ovrgb" -type "float3" 0.02 0.02 0.02 ;
	setAttr ".rnd" no;
	setAttr ".cap" -type "double2" 1.41732 0.94488 ;
	setAttr -av ".hfa";
	setAttr ".ovr" 1.3;
	setAttr ".ow" 30;
	setAttr ".imn" -type "string" "camera1";
	setAttr ".den" -type "string" "camera1_depth";
	setAttr ".man" -type "string" "camera1_mask";
	setAttr ".dgc" -type "float3" 0 0 0 ;
createNode transform -n "Ctrl_Cam" -p "Flux_Cam_Rig";
	rename -uid "54D804D0-4005-3616-CF58-D4A920B08036";
createNode transform -n "Ctrl_Gen_Cam" -p "Ctrl_Cam";
	rename -uid "80E43DC7-4285-6D8D-B784-5C9A5F74F80F";
	addAttr -ci true -sn "HideRigInOutliner" -ln "HideRigInOutliner" -min 0 -max 1 
		-at "bool";
	addAttr -ci true -sn "SETTINGS" -ln "SETTINGS" -min 0 -max 0 -en "------------" 
		-at "enum";
	addAttr -ci true -sn "Hide_On_PlayBack" -ln "Hide_On_PlayBack" -nn "Hide On Play Back" 
		-min 0 -max 1 -smn -2999 -smx 2999 -at "bool";
	addAttr -ci true -sn "Cam_Lock_Selection" -ln "Cam_Lock_Selection" -nn "Cam Lock Selection" 
		-min 0 -max 1 -smn -2999 -smx 2999 -at "bool";
	addAttr -ci true -sn "AdjustCamCtrl" -ln "AdjustCamCtrl" -nn "Adjust Cam Ctrl" -min 
		0 -max 1 -smn -2999 -smx 2999 -at "bool";
	addAttr -ci true -sn "SettingsCamCtrl" -ln "SettingsCamCtrl" -nn "Settings Cam Ctrl" 
		-min 0 -max 1 -smn -2999 -smx 2999 -at "bool";
	addAttr -ci true -sn "RollCamCtrl" -ln "RollCamCtrl" -nn "Roll Cam Ctrl" -min 0 
		-max 1 -smn -2999 -smx 2999 -at "bool";
	addAttr -ci true -sn "AimCamCtrl" -ln "AimCamCtrl" -nn "Aim Cam Ctrl" -min 0 -max 
		1 -smn -2999 -smx 2999 -at "bool";
	setAttr -l on ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 13;
	setAttr -k off ".sx";
	setAttr -k off ".sy";
	setAttr -l on ".opm";
	setAttr -l on -cb on ".HideRigInOutliner" yes;
	setAttr -cb on ".SETTINGS";
	setAttr -cb on ".Hide_On_PlayBack" yes;
	setAttr -cb on ".Cam_Lock_Selection" yes;
	setAttr -cb on ".AdjustCamCtrl" yes;
	setAttr -k on ".SettingsCamCtrl" yes;
	setAttr -cb on ".RollCamCtrl" yes;
	setAttr -cb on ".AimCamCtrl" yes;
createNode nurbsCurve -n "Ctrl_Gen_CamShape" -p "Ctrl_Gen_Cam";
	rename -uid "524A96FA-455E-FEC5-94FD-F8A34BF80BCB";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 13;
	setAttr ".ls" 3;
	setAttr ".cc" -type "nurbsCurve" 
		1 4 0 no 3
		5 0 1 2 3 4
		5
		-0.66766296004087011 -0.34144123567665274 -0.47487318784373472
		0.66766296004087011 -0.34144123567665274 -0.47487318784373472
		0.66766296004087011 -0.34144123567665274 2.0394092868244336
		-0.66766296004087011 -0.34144123567665274 2.0394092868244336
		-0.66766296004087011 -0.34144123567665274 -0.47487318784373472
		;
createNode transform -n "Ctrl_Adjust_Cam" -p "Ctrl_Gen_Cam";
	rename -uid "2FAE63EF-4F36-ECF4-D2FA-8587C5633593";
	setAttr -l on -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 14;
	setAttr -l on -k off ".sx";
	setAttr -l on -k off ".sy";
	setAttr -l on -k off ".sz";
	setAttr -l on ".opm";
createNode nurbsCurve -n "Ctrl_Adjust_CamShape" -p "Ctrl_Adjust_Cam";
	rename -uid "5640A5DE-4910-51B2-834E-F8B342E24404";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 14;
	setAttr ".cc" -type "nurbsCurve" 
		1 4 0 no 3
		5 0 1 2 3 4
		5
		-0.4839377016219229 -0.34144123567665274 -0.21773195050965122
		0.4839377016219229 -0.34144123567665274 -0.21773195050965122
		0.4839377016219229 -0.34144123567665274 1.7822680494903487
		-0.4839377016219229 -0.34144123567665274 1.7822680494903487
		-0.4839377016219229 -0.34144123567665274 -0.21773195050965122
		;
createNode transform -n "Ctrl_Aim_Cam" -p "Ctrl_Adjust_Cam";
	rename -uid "57390CCB-4687-F051-7960-5294F73FBC6E";
	addAttr -ci true -sn "antOffsetStack" -ln "antOffsetStack" -dt "string";
	addAttr -ci true -sn "artMtxCon" -ln "artMtxCon" -dt "string";
	setAttr -k off ".v";
	setAttr -l on -k off ".rx";
	setAttr -l on -k off ".ry";
	setAttr -l on -k off ".rz";
	setAttr -l on -k off ".sx";
	setAttr -l on -k off ".sy";
	setAttr -l on -k off ".sz";
	setAttr ".opm" -type "matrix" 1 0 0 0 0 1 0 0 0 0 1 0 0 0 -5 1;
	setAttr ".antOffsetStack" -type "string" "{\"groups\": [], \"ctrl_m\": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, -5.0, 1.0], \"ctrl_opm\": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]}";
	setAttr ".artMtxCon" -type "string" "aim|direct|Ctrl_Adjust_Cam";
createNode nurbsCurve -n "curveShape2" -p "Ctrl_Aim_Cam";
	rename -uid "F6CB16E2-43A0-38B3-5351-FE93E77AF840";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovrgbf" yes;
	setAttr ".ovrgb" -type "float3" 1 0 0 ;
	setAttr ".ls" 2;
	setAttr ".cc" -type "nurbsCurve" 
		1 16 0 no 3
		17 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16
		17
		4.3316672780428504e-26 0 -1.1344937212269447e-07
		1.7683983683390738e-17 0.18839476296645122 0.36602196859277997
		1.326298777337223e-17 0.14795783894925346 0.32259413287588984
		-8.8419917767203522e-18 0.10185841321630273 0.29030838834292905
		8.8419918633537148e-18 0.051961780450435667 0.2702175310112766
		8.8419918633537148e-18 0 0.26319889089541598
		4.3316672780428504e-26 0 -1.1344937212269447e-07
		-0.22522639426890995 0 0.36602196859277997
		-0.17688395391486905 0 0.32259413287588984
		-0.12177197907961937 0 0.29030838834292905
		-0.062120434062853558 0 0.2702175310112766
		8.8419918633537148e-18 0 0.26319889089541598
		0.062120434062853586 0 0.27021753101127671
		0.12177197907961942 0 0.29030838834292905
		0.17688395391486914 0 0.32259413287588984
		0.22522639426890995 0 0.36602196859277997
		4.3316672780428504e-26 0 -1.1344937212269447e-07
		;
createNode transform -n "Ctrl_Up_Cam" -p "Ctrl_Adjust_Cam";
	rename -uid "CDCB6CE4-4A6C-3172-4989-9F8E43448816";
	addAttr -ci true -sn "antOffsetStack" -ln "antOffsetStack" -dt "string";
	addAttr -ci true -sn "artMtxCon" -ln "artMtxCon" -dt "string";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 14;
	setAttr -l on -k off ".tz";
	setAttr -l on -k off ".rx";
	setAttr -l on -k off ".ry";
	setAttr -l on -k off ".rz";
	setAttr -l on -k off ".sx";
	setAttr -l on -k off ".sy";
	setAttr -l on -k off ".sz";
	setAttr ".opm" -type "matrix" 1 0 0 0 0 1 0 0 0 0 1 0 0 2 0 1;
	setAttr ".antOffsetStack" -type "string" "{\"groups\": [], \"ctrl_m\": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 2.0, 0.0, 1.0], \"ctrl_opm\": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]}";
	setAttr ".artMtxCon" -type "string" "aim|direct|Ctrl_Adjust_Cam";
createNode nurbsCurve -n "curveShape3" -p "Ctrl_Up_Cam";
	rename -uid "517FDA93-4401-06A5-161F-A79FF733BAD8";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovrgbf" yes;
	setAttr ".ovc" 14;
	setAttr ".ovrgb" -type "float3" 0 0.866 0 ;
	setAttr ".ls" 2;
	setAttr ".cc" -type "nurbsCurve" 
		1 40 0 no 3
		41 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27
		 28 29 30 31 32 33 34 35 36 37 38 39 40
		41
		0.84204200472477586 -0.26869224391340407 -3.3306690738754696e-16
		0.81626192038570999 -0.16183353721324867 0.16813055366632024
		0.76147924116519206 -0.060273609357731628 0.33626110733263881
		0.68027197549713136 0.032675802875254512 0.50439166099896149
		0.68027197549713136 0.032675802875254512 0.33626110733263881
		0.68027197549713136 0.032675802875254512 0.16813055366632024
		0.57521813181543258 0.11348218025595014 0.16813055366631935
		0.45018472277095861 0.17949613336203774 0.16813055366631979
		0.30903876101456657 0.22850983767491817 0.16813055366632113
		0.15822526763102412 0.25853625112785472 0.16710327940766745
		1.5820678100908481e-15 0.2686922439134044 0.16710327940766612
		-0.1582252676310231 0.25853625112785528 0.16710327940766745
		-0.30903876101456473 0.22850983767491884 0.16813055366632113
		-0.45018472277095734 0.17949613336203796 0.16813055366632024
		-0.57521813181543291 0.11348218025595036 0.16813055366631935
		-0.6802719754971307 0.032675802875255733 0.1681305536663189
		-0.6802719754971307 0.032675802875255733 0.33626110733263881
		-0.6802719754971307 0.032675802875255733 0.50439166099896104
		-0.76147924116519028 -0.060273609357730296 0.33626110733263881
		-0.81626192038570955 -0.16183353721324889 0.16813055366632024
		-0.84204200472477586 -0.26869224391340341 -3.3306690738754696e-16
		-0.81626192038570955 -0.16183353721324889 -0.16813055366632157
		-0.76147924116519028 -0.060273609357730296 -0.33626110733264014
		-0.6802719754971307 0.032675802875255733 -0.50439166099896149
		-0.6802719754971307 0.032675802875255733 -0.33626110733264125
		-0.6802719754971307 0.032675802875255733 -0.16813055366632113
		-0.5752181318154318 0.11348218025595025 -0.16813055366632068
		-0.45018472277095734 0.17949613336203796 -0.16813055366632135
		-0.30903876101456473 0.22850983767491884 -0.16813055366632157
		-0.1582252676310231 0.25853625112785528 -0.16710327940766823
		1.5820678100908481e-15 0.2686922439134044 -0.167103279407668
		0.15725851446831013 0.2585362511278535 -0.1681305536663209
		0.30903876101456657 0.22850983767491817 -0.16813055366632079
		0.45018472277095861 0.17949613336203774 -0.16813055366632135
		0.57521813181543391 0.11348218025595025 -0.16813055366632113
		0.68027197549713136 0.032675802875254512 -0.16813055366632113
		0.68027197549713136 0.032675802875254512 -0.33626110733264125
		0.68027197549713136 0.032675802875254512 -0.50439166099896104
		0.76147924116519206 -0.060273609357731628 -0.33626110733264014
		0.81626192038570999 -0.16183353721324867 -0.16813055366632157
		0.84204200472477586 -0.26869224391340407 -3.3306690738754696e-16
		;
createNode transform -n "Ctrl_Setting_Cam" -p "Ctrl_Adjust_Cam";
	rename -uid "F0C44718-4B66-CA1A-2D46-219F61DCF4CE";
	addAttr -ci true -sn "CAMERA" -ln "CAMERA" -min 0 -max 0 -en "---------------" 
		-at "enum";
	addAttr -ci true -k true -sn "Focal_Length" -ln "Focal_Length" -dv 35 -min 1 -max 
		500 -at "double";
	addAttr -ci true -k true -sn "Camera_Scale" -ln "Camera_Scale" -dv 1 -min 0.001 
		-max 1000 -at "double";
	addAttr -ci true -sn "FILM_BACK" -ln "FILM_BACK" -min 0 -max 0 -en "---------------" 
		-at "enum";
	addAttr -ci true -k true -sn "Horizontal_Aperture" -ln "Horizontal_Aperture" -dv 
		1.41732 -min 0.01 -max 100 -at "double";
	addAttr -ci true -k true -sn "Vertical_Aperture" -ln "Vertical_Aperture" -dv 0.94488 
		-min 0.01 -max 100 -at "double";
	addAttr -ci true -k true -sn "Lens_Squeeze" -ln "Lens_Squeeze" -dv 1 -min 0.01 -max 
		10 -at "double";
	addAttr -ci true -k true -sn "Film_Fit" -ln "Film_Fit" -min 0 -max 3 -en "Fill:Horizontal:Vertical:Overscan" 
		-at "enum";
	addAttr -ci true -k true -sn "Film_Fit_Offset" -ln "Film_Fit_Offset" -min -100 -max 
		100 -at "double";
	addAttr -ci true -k true -sn "Film_Offset_H" -ln "Film_Offset_H" -min -100 -max 
		100 -at "double";
	addAttr -ci true -k true -sn "Film_Offset_V" -ln "Film_Offset_V" -min -100 -max 
		100 -at "double";
	addAttr -ci true -sn "FILM_ROLL" -ln "FILM_ROLL" -min 0 -max 0 -en "---------------" 
		-at "enum";
	addAttr -ci true -k true -sn "Roll" -ln "Roll" -min -360 -max 360 -at "double";
	addAttr -ci true -k true -sn "Roll_Pivot_H" -ln "Roll_Pivot_H" -min -10 -max 10 
		-at "double";
	addAttr -ci true -k true -sn "Roll_Pivot_V" -ln "Roll_Pivot_V" -min -10 -max 10 
		-at "double";
	addAttr -ci true -k true -sn "Roll_Order" -ln "Roll_Order" -min 0 -max 1 -en "Rotate_Translate:Translate_Rotate" 
		-at "enum";
	addAttr -ci true -sn "DEPTH_OF_FIELD" -ln "DEPTH_OF_FIELD" -min 0 -max 0 -en "---------------" 
		-at "enum";
	addAttr -ci true -k true -sn "DOF_Enable" -ln "DOF_Enable" -min 0 -max 1 -at "bool";
	addAttr -ci true -k true -sn "Focus_Distance" -ln "Focus_Distance" -dv 5 -min 0.001 
		-max 1000000 -at "double";
	addAttr -ci true -k true -sn "F_Stop" -ln "F_Stop" -dv 5.6 -min 0.001 -max 1000 
		-at "double";
	addAttr -ci true -k true -sn "Focus_Region_Scale" -ln "Focus_Region_Scale" -dv 1 
		-min 0.001 -max 1000 -at "double";
	addAttr -ci true -sn "CLIPPING" -ln "CLIPPING" -min 0 -max 0 -en "---------------" 
		-at "enum";
	addAttr -ci true -k true -sn "Near_Clip" -ln "Near_Clip" -dv 0.1 -min 0.001 -max 
		1000000 -at "double";
	addAttr -ci true -k true -sn "Far_Clip" -ln "Far_Clip" -dv 10000 -min 0.01 -max 
		1000000 -at "double";
	addAttr -ci true -sn "PAN_ZOOM_2D" -ln "PAN_ZOOM_2D" -min 0 -max 0 -en "---------------" 
		-at "enum";
	addAttr -ci true -k true -sn "Render_PanZoom" -ln "Render_PanZoom" -min 0 -max 1 
		-at "bool";
	addAttr -ci true -k true -sn "Zoom" -ln "Zoom" -dv 1 -min 0.001 -max 1000 -at "double";
	addAttr -ci true -k true -sn "Pan_H" -ln "Pan_H" -min -1000 -max 1000 -at "double";
	addAttr -ci true -k true -sn "Pan_V" -ln "Pan_V" -min -1000 -max 1000 -at "double";
	addAttr -ci true -k true -sn "Pre_Scale" -ln "Pre_Scale" -dv 1 -min 0.001 -max 1000 
		-at "double";
	addAttr -ci true -k true -sn "Post_Scale" -ln "Post_Scale" -dv 1 -min 0.001 -max 
		1000 -at "double";
	addAttr -ci true -sn "CAMERA_SHAKE" -ln "CAMERA_SHAKE" -min 0 -max 0 -en "---------------" 
		-at "enum";
	addAttr -ci true -k true -sn "Shake_Enable" -ln "Shake_Enable" -min 0 -max 1 -at "bool";
	addAttr -ci true -k true -sn "Shake_H" -ln "Shake_H" -min -1000 -max 1000 -at "double";
	addAttr -ci true -k true -sn "Shake_V" -ln "Shake_V" -min -1000 -max 1000 -at "double";
	addAttr -ci true -k true -sn "Shake_Overscan_Enable" -ln "Shake_Overscan_Enable" 
		-min 0 -max 1 -at "bool";
	addAttr -ci true -k true -sn "Shake_Overscan" -ln "Shake_Overscan" -dv 1 -min 0.001 
		-max 100 -at "double";
	addAttr -ci true -sn "MOTION_BLUR" -ln "MOTION_BLUR" -min 0 -max 0 -en "---------------" 
		-at "enum";
	addAttr -ci true -k true -sn "Shutter_Angle" -ln "Shutter_Angle" -dv 144 -min 0 
		-max 360 -at "double";
	addAttr -ci true -sn "PROJECTION" -ln "PROJECTION" -min 0 -max 0 -en "---------------" 
		-at "enum";
	addAttr -ci true -k true -sn "Orthographic" -ln "Orthographic" -min 0 -max 1 -at "bool";
	addAttr -ci true -k true -sn "Orthographic_Width" -ln "Orthographic_Width" -dv 30 
		-min 0.001 -max 100000 -at "double";
	addAttr -ci true -sn "DISPLAY" -ln "DISPLAY" -min 0 -max 0 -en "---------------" 
		-at "enum";
	addAttr -ci true -k true -sn "Display_Film_Gate" -ln "Display_Film_Gate" -min 0 
		-max 1 -at "bool";
	addAttr -ci true -k true -sn "Display_Gate_Mask" -ln "Display_Gate_Mask" -dv 1 -min 
		0 -max 1 -at "bool";
	addAttr -ci true -k true -sn "Display_Resolution" -ln "Display_Resolution" -dv 1 
		-min 0 -max 1 -at "bool";
	addAttr -ci true -k true -sn "Display_Safe_Action" -ln "Display_Safe_Action" -min 
		0 -max 1 -at "bool";
	addAttr -ci true -k true -sn "Display_Safe_Title" -ln "Display_Safe_Title" -min 
		0 -max 1 -at "bool";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 14;
	setAttr -l on -k off ".tx";
	setAttr -l on -k off ".ty";
	setAttr -l on -k off ".tz";
	setAttr -l on -k off ".rx";
	setAttr -l on -k off ".ry";
	setAttr -l on -k off ".rz";
	setAttr -l on -k off ".sx";
	setAttr -l on -k off ".sy";
	setAttr -l on -k off ".sz";
	setAttr -l on ".opm" -type "matrix" 1 0 0 0 0 1 0 0 0 0 1 0 0 1.0871771251821767 1.4679392244251059 1;
	setAttr -l on -cb on ".CAMERA";
	setAttr -k on ".Focal_Length";
	setAttr -l on -cb on ".FILM_BACK";
	setAttr -k on ".Horizontal_Aperture";
	setAttr -k on ".Vertical_Aperture";
	setAttr -k on ".Lens_Squeeze";
	setAttr -k on ".Film_Fit";
	setAttr -k on ".Film_Fit_Offset";
	setAttr -k on ".Film_Offset_H";
	setAttr -k on ".Film_Offset_V";
	setAttr -l on -cb on ".FILM_ROLL";
	setAttr -k on ".Roll";
	setAttr -k on ".Roll_Pivot_H";
	setAttr -k on ".Roll_Pivot_V";
	setAttr -k on ".Roll_Order";
	setAttr -l on -cb on ".DEPTH_OF_FIELD";
	setAttr -k on ".DOF_Enable";
	setAttr -k on ".Focus_Distance";
	setAttr -k on ".F_Stop";
	setAttr -k on ".Focus_Region_Scale";
	setAttr -l on -cb on ".CLIPPING";
	setAttr -k on ".Near_Clip";
	setAttr -k on ".Far_Clip";
	setAttr -l on -cb on ".PAN_ZOOM_2D";
	setAttr -k on ".Render_PanZoom";
	setAttr -k on ".Zoom";
	setAttr -k on ".Pan_H";
	setAttr -k on ".Pan_V";
	setAttr -k on ".Pre_Scale";
	setAttr -k on ".Post_Scale";
	setAttr -l on -cb on ".CAMERA_SHAKE";
	setAttr -k on ".Shake_Enable";
	setAttr -k on ".Shake_H";
	setAttr -k on ".Shake_V";
	setAttr -k on ".Shake_Overscan_Enable";
	setAttr -k on ".Shake_Overscan";
	setAttr -l on -cb on ".MOTION_BLUR";
	setAttr -k on ".Shutter_Angle";
	setAttr -l on -cb on ".PROJECTION";
	setAttr -k on ".Orthographic";
	setAttr -k on ".Orthographic_Width";
	setAttr -l on -cb on ".DISPLAY";
	setAttr -k on ".Display_Film_Gate";
	setAttr -k on ".Display_Gate_Mask";
	setAttr -k on ".Display_Resolution";
	setAttr -k on ".Display_Safe_Action";
	setAttr -k on ".Display_Safe_Title";
createNode nurbsCurve -n "Ctrl_Settings_CamShape" -p "Ctrl_Setting_Cam";
	rename -uid "E5762E51-4540-5671-E741-8889FB2398A5";
	setAttr -k off ".v";
	setAttr ".ove" yes;
	setAttr ".ovc" 14;
	setAttr ".ls" 2;
	setAttr ".cc" -type "nurbsCurve" 
		1 12 0 no 3
		13 0 4.7999999999999998 9.5999999999999996 12.800000000000001 17.600000000000001
		 22.399999999999999 25.600000000000001 30.399999999999999 35.200000000000003 38.399999999999999
		 43.200000000000003 48 51.200000000000003
		13
		-0.07084305159394888 -0.28337220637579641 0
		-0.07084305159394888 -0.070843051593948436 0
		-0.28337220637579574 -0.070843051593948436 0
		-0.28337220637579574 0.07084305159394888 0
		-0.07084305159394888 0.07084305159394888 0
		-0.07084305159394888 0.28337220637579663 0
		0.07084305159394888 0.28337220637579663 0
		0.07084305159394888 0.07084305159394888 0
		0.28337220637579574 0.07084305159394888 0
		0.28337220637579574 -0.070843051593948436 0
		0.07084305159394888 -0.070843051593948436 0
		0.07084305159394888 -0.28337220637579641 0
		-0.07084305159394888 -0.28337220637579641 0
		;
createNode transform -n "DO_NOT_TOUCH" -p "Flux_Cam_Rig";
	rename -uid "6A2CA128-41B5-09C6-674E-8F9F0122D9DB";
createNode transform -n "Crv_Aim_Guide" -p "DO_NOT_TOUCH";
	rename -uid "C647EFD6-46D3-2EFD-6480-5C981728F51C";
	setAttr ".ove" yes;
	setAttr ".ovc" 1;
createNode nurbsCurve -n "Crv_Aim_GuideShape" -p "Crv_Aim_Guide";
	rename -uid "89537EF6-4251-65BA-7CF4-7E9B2543E568";
	setAttr -k off ".v";
	setAttr ".ovdt" 2;
	setAttr ".ove" yes;
	setAttr ".ovc" 1;
	setAttr -s 2 ".cp";
	setAttr ".cc" -type "nurbsCurve" 
		1 1 0 no 3
		2 0 1
		2
		0 0 0
		0 0 -5
		;
createNode lookAt -n "Cam_Guides" -p "DO_NOT_TOUCH";
	rename -uid "9456A51A-4C9B-7509-0E4B-AF8B81ACD68F";
	setAttr ".v" no;
	setAttr ".a" -type "double3" 0 0 -1 ;
	setAttr ".db" 5;
createNode transform -n "Loc_Cam_Aim" -p "Cam_Guides";
	rename -uid "4054337D-4070-13E3-7377-2581D2BE4021";
	addAttr -ci true -sn "artMtxCon" -ln "artMtxCon" -dt "string";
	setAttr ".drp" yes;
	setAttr ".artMtxCon" -type "string" "point|offsetParentMatrix|Ctrl_Aim_Cam";
createNode locator -n "Loc_Cam_AimShape" -p "Loc_Cam_Aim";
	rename -uid "A8DF5096-4907-171C-D714-5399D83EFCC7";
	setAttr -k off ".v" no;
createNode transform -n "Loc_Cam_Up" -p "Cam_Guides";
	rename -uid "A37D5D10-49D9-C71C-C764-82A2F4029122";
	addAttr -ci true -sn "artMtxCon" -ln "artMtxCon" -dt "string";
	setAttr -l on ".v";
	setAttr -l on ".tx";
	setAttr -l on ".ty";
	setAttr -l on ".tz";
	setAttr -l on ".rx";
	setAttr -l on ".ry";
	setAttr -l on ".rz";
	setAttr -l on ".sx";
	setAttr -l on ".sy";
	setAttr -l on ".sz";
	setAttr ".drp" yes;
	setAttr ".artMtxCon" -type "string" "point|offsetParentMatrix|camera1_up_Ctrl";
createNode locator -n "Loc_Cam_UpShape" -p "Loc_Cam_Up";
	rename -uid "CE770077-462C-DFD8-B338-EB85E6E948DB";
	setAttr -k off ".v" no;
createNode transform -n "Loc_Cam" -p "Cam_Guides";
	rename -uid "F9FDCE83-4F60-F7AE-B6C4-939C613F257F";
	addAttr -ci true -sn "artMtxCon" -ln "artMtxCon" -dt "string";
	setAttr ".artMtxCon" -type "string" "point|offsetParentMatrix|Ctrl_Adjust_Cam";
createNode locator -n "Loc_CamShape" -p "Loc_Cam";
	rename -uid "5C050A1F-4EC6-EA3A-13A2-7D9DD4AB36AB";
	setAttr -k off ".v";
createNode transform -n "Loc_Up_Fix_Cam" -p "Loc_Cam";
	rename -uid "39E1D448-4D95-8BB1-E52D-0088BFA4A039";
	setAttr ".t" -type "double3" 0 2 0 ;
createNode locator -n "Loc_Up_Fix_CamShape" -p "Loc_Up_Fix_Cam";
	rename -uid "D29BFA00-4451-8673-5AFC-7EB97DCA734F";
	setAttr -k off ".v";
createNode pickMatrix -n "pck_Cam_opm";
	rename -uid "57CB7E50-4494-0105-5BA6-258EC66F806E";
	setAttr ".sca" no;
	setAttr ".she" no;
createNode multMatrix -n "mmx_Cam_opm";
	rename -uid "D1882695-46B9-35FF-BDC8-DB8C6AEB4857";
	setAttr -s 2 ".i";
createNode unitConversion -n "unitConversion1";
	rename -uid "CD1FDF40-4E00-50A0-F594-FC835A19701C";
	setAttr ".cf" 0.017453292519943295;
createNode unitConversion -n "unitConversion2";
	rename -uid "A9CA29FA-4E5E-9466-72DC-A69CD7F4727D";
	setAttr ".cf" 0.017453292519943295;
createNode remapValue -n "Remap_Lock_Cam";
	rename -uid "5D41D8B4-4B7D-B919-7EFE-2598E37BD623";
	setAttr ".omx" 2;
	setAttr -s 2 ".vl[0:1]"  0 0 1 1 1 1;
	setAttr -s 2 ".cl";
	setAttr ".cl[0].clp" 0;
	setAttr ".cl[0].clc" -type "float3" 0 0 0 ;
	setAttr ".cl[0].cli" 1;
	setAttr ".cl[1].clp" 1;
	setAttr ".cl[1].clc" -type "float3" 1 1 1 ;
	setAttr ".cl[1].cli" 1;
createNode decomposeMatrix -n "dcm_Ctrl_Aim_Cam_dir1";
	rename -uid "52D5CC1A-4025-3641-85F6-E88C87D2D00A";
createNode multMatrix -n "mmx_Ctrl_Aim_Cam_local1";
	rename -uid "542F0BB4-40FD-9B73-9CA1-D39E570EB426";
	setAttr -s 3 ".i";
	setAttr ".i[2]" -type "matrix" 1 0 0 0 0 1 0 0 0 0 1 0 0 0 5 1;
createNode aimMatrix -n "aim_Ctrl_Aim_Cam_mtx1";
	rename -uid "1741B123-44BC-823A-4D94-56A69098D2BC";
	setAttr ".pmi" -type "double3" 0 0 1 ;
	setAttr ".sm" 2;
	setAttr ".smiv" -type "double3" 0 1 0 ;
createNode multMatrix -n "mmx_Ctrl_Aim_Cam_aimIn1";
	rename -uid "2FD1A9DB-4EA6-C334-CCA5-1FAFEF2A6B15";
	setAttr -s 3 ".i";
createNode composeMatrix -n "cmp_Ctrl_Aim_Cam_aimT";
	rename -uid "DB2D719B-4656-731F-B292-6396FAE5B090";
createNode decomposeMatrix -n "dcm_Ctrl_Up_Cam_dir1";
	rename -uid "68A6A272-4824-E281-9F14-3996915D5DB4";
createNode multMatrix -n "mmx_Ctrl_Up_Cam_local1";
	rename -uid "270BEFEE-42A6-325E-DE31-179D7C9A6CF0";
	setAttr -s 3 ".i";
	setAttr ".i[2]" -type "matrix" 1 0 0 0 0 1 0 0 0 0 1 0 0 -2 0 1;
createNode aimMatrix -n "aim_Ctrl_Up_Cam_mtx1";
	rename -uid "C3BFF420-4502-161B-3617-E1B3D539C047";
	setAttr ".pmi" -type "double3" 0 -1 0 ;
	setAttr ".smi" -type "double3" 0 0 -1 ;
	setAttr ".sm" 2;
	setAttr ".smiv" -type "double3" 0 0 -1 ;
createNode multMatrix -n "mmx_Ctrl_Up_Cam_aimIn1";
	rename -uid "3AB5A38C-43BB-9DD8-6846-57A1298BA17F";
	setAttr -s 3 ".i";
createNode composeMatrix -n "cmp_Ctrl_Up_Cam_aimT";
	rename -uid "1C0F8B40-48E6-4A65-16E5-23A4C8CAE289";
createNode pickMatrix -n "pck_Loc_Cam_Aim_opm";
	rename -uid "91B291F8-4FC7-FCBE-1499-9F9131409EE7";
	setAttr ".sca" no;
	setAttr ".she" no;
	setAttr ".rot" no;
createNode multMatrix -n "mmx_Loc_Cam_Aim_local1";
	rename -uid "BED3CCE7-4FD6-4F57-C995-379FA17F3B87";
	setAttr -s 2 ".i";
createNode pickMatrix -n "pck_camera1_up_opm";
	rename -uid "6678BC35-4989-7BF6-957C-FCBCD7E8D667";
	setAttr ".sca" no;
	setAttr ".she" no;
	setAttr ".rot" no;
createNode multMatrix -n "mmx_camera1_up_local";
	rename -uid "126E6B67-4FA3-1509-4DD8-0AAEEBE2D12A";
	setAttr -s 2 ".i";
createNode pickMatrix -n "pck_Loc_Cam_opm";
	rename -uid "28F50626-4C30-4FB2-6427-8FAE69A13CDA";
	setAttr ".sca" no;
	setAttr ".she" no;
	setAttr ".rot" no;
createNode multMatrix -n "mmx_Loc_Cam_local";
	rename -uid "E6E1FDC2-4CE2-9E2C-63DE-809F4F4398B6";
	setAttr -s 2 ".i";
connectAttr "Cam_Guides.crx" "Cam.rx" -l on;
connectAttr "Cam_Guides.cry" "Cam.ry" -l on;
connectAttr "Cam_Guides.crz" "Cam.rz" -l on;
connectAttr "pck_Cam_opm.tmat" "Cam.opm";
connectAttr "Ctrl_Setting_Cam.Horizontal_Aperture" "CamShape.hfa";
connectAttr "Ctrl_Setting_Cam.Vertical_Aperture" "CamShape.vfa";
connectAttr "Cam_Guides.db" "CamShape.coi";
connectAttr "Ctrl_Gen_Cam.sz" "CamShape.lls";
connectAttr "Ctrl_Setting_Cam.Focal_Length" "CamShape.fl";
connectAttr "Ctrl_Setting_Cam.Film_Fit" "CamShape.ff";
connectAttr "Ctrl_Setting_Cam.Film_Fit_Offset" "CamShape.ffo";
connectAttr "Ctrl_Setting_Cam.Film_Offset_H" "CamShape.hfo";
connectAttr "Ctrl_Setting_Cam.Film_Offset_V" "CamShape.vfo";
connectAttr "Ctrl_Setting_Cam.Lens_Squeeze" "CamShape.lsr";
connectAttr "Ctrl_Setting_Cam.DOF_Enable" "CamShape.dof";
connectAttr "Ctrl_Setting_Cam.Focus_Distance" "CamShape.fd";
connectAttr "Ctrl_Setting_Cam.F_Stop" "CamShape.fs";
connectAttr "Ctrl_Setting_Cam.Near_Clip" "CamShape.ncp";
connectAttr "Ctrl_Setting_Cam.Far_Clip" "CamShape.fcp";
connectAttr "Ctrl_Setting_Cam.Pan_H" "CamShape.hpn";
connectAttr "Ctrl_Setting_Cam.Pan_V" "CamShape.vpn";
connectAttr "Ctrl_Setting_Cam.Zoom" "CamShape.zom";
connectAttr "Ctrl_Setting_Cam.Render_PanZoom" "CamShape.rpz";
connectAttr "Ctrl_Setting_Cam.Shake_Enable" "CamShape.se";
connectAttr "Ctrl_Setting_Cam.Shake_H" "CamShape.hs";
connectAttr "Ctrl_Setting_Cam.Shake_V" "CamShape.vs";
connectAttr "unitConversion1.o" "CamShape.frv";
connectAttr "Ctrl_Setting_Cam.Roll_Pivot_H" "CamShape.hrp";
connectAttr "Ctrl_Setting_Cam.Roll_Pivot_V" "CamShape.vrp";
connectAttr "Ctrl_Setting_Cam.Roll_Order" "CamShape.fro";
connectAttr "Ctrl_Setting_Cam.Pre_Scale" "CamShape.psc";
connectAttr "Ctrl_Setting_Cam.Post_Scale" "CamShape.ptsc";
connectAttr "unitConversion2.o" "CamShape.sa";
connectAttr "Remap_Lock_Cam.ov" "CamShape.ovdt";
connectAttr "Ctrl_Setting_Cam.Focus_Region_Scale" "CamShape.frs";
connectAttr "Ctrl_Setting_Cam.Shake_Overscan_Enable" "CamShape.soe";
connectAttr "Ctrl_Setting_Cam.Shake_Overscan" "CamShape.sos";
connectAttr "Ctrl_Setting_Cam.Orthographic" "CamShape.o";
connectAttr "Ctrl_Setting_Cam.Orthographic_Width" "CamShape.ow";
connectAttr "Ctrl_Setting_Cam.Display_Film_Gate" "CamShape.dfg";
connectAttr "Ctrl_Setting_Cam.Display_Gate_Mask" "CamShape.dgm";
connectAttr "Ctrl_Setting_Cam.Display_Resolution" "CamShape.dr";
connectAttr "Ctrl_Setting_Cam.Display_Safe_Action" "CamShape.dsa";
connectAttr "Ctrl_Setting_Cam.Display_Safe_Title" "CamShape.dst";
connectAttr "Ctrl_Gen_Cam.Hide_On_PlayBack" "Ctrl_Cam.hpb";
connectAttr "Ctrl_Gen_Cam.sz" "Ctrl_Gen_Cam.sx" -l on;
connectAttr "Ctrl_Gen_Cam.sz" "Ctrl_Gen_Cam.sy" -l on;
connectAttr "Ctrl_Gen_Cam.AdjustCamCtrl" "Ctrl_Adjust_CamShape.v";
connectAttr "Ctrl_Gen_Cam.AimCamCtrl" "Ctrl_Aim_Cam.v" -l on;
connectAttr "dcm_Ctrl_Aim_Cam_dir1.or" "Ctrl_Aim_Cam.r";
connectAttr "Ctrl_Gen_Cam.HideRigInOutliner" "curveShape2.hio";
connectAttr "Ctrl_Gen_Cam.RollCamCtrl" "Ctrl_Up_Cam.v" -l on;
connectAttr "dcm_Ctrl_Up_Cam_dir1.or" "Ctrl_Up_Cam.r";
connectAttr "Ctrl_Gen_Cam.HideRigInOutliner" "curveShape3.hio";
connectAttr "Ctrl_Gen_Cam.SettingsCamCtrl" "Ctrl_Setting_Cam.v" -l on;
connectAttr "Ctrl_Gen_Cam.Hide_On_PlayBack" "DO_NOT_TOUCH.hpb";
connectAttr "Ctrl_Gen_Cam.HideRigInOutliner" "DO_NOT_TOUCH.hio";
connectAttr "Ctrl_Gen_Cam.HideRigInOutliner" "Crv_Aim_Guide.hio";
connectAttr "Loc_CamShape.wp" "Crv_Aim_GuideShape.cp[0]";
connectAttr "Loc_Cam_AimShape.wp" "Crv_Aim_GuideShape.cp[1]";
connectAttr "Ctrl_Gen_Cam.HideRigInOutliner" "Crv_Aim_GuideShape.hio";
connectAttr "Loc_Cam_Aim.tx" "Cam_Guides.tg[0].ttx";
connectAttr "Loc_Cam_Aim.ty" "Cam_Guides.tg[0].tty";
connectAttr "Loc_Cam_Aim.tz" "Cam_Guides.tg[0].ttz";
connectAttr "Loc_Cam_Aim.rp" "Cam_Guides.tg[0].trp";
connectAttr "Loc_Cam_Aim.rpt" "Cam_Guides.tg[0].trt";
connectAttr "Loc_Cam_Aim.pm" "Cam_Guides.tg[0].tpm";
connectAttr "Cam.pim" "Cam_Guides.cpim";
connectAttr "Cam.t" "Cam_Guides.ct";
connectAttr "Cam.rp" "Cam_Guides.crp";
connectAttr "Cam.rpt" "Cam_Guides.crt";
connectAttr "Loc_Cam_Up.wm" "Cam_Guides.wum";
connectAttr "pck_Loc_Cam_Aim_opm.tmat" "Loc_Cam_Aim.opm";
connectAttr "Ctrl_Gen_Cam.HideRigInOutliner" "Loc_Cam_Aim.hio";
connectAttr "Ctrl_Gen_Cam.HideRigInOutliner" "Loc_Cam_AimShape.hio";
connectAttr "pck_camera1_up_opm.tmat" "Loc_Cam_Up.opm";
connectAttr "Ctrl_Gen_Cam.HideRigInOutliner" "Loc_Cam_Up.hio";
connectAttr "Ctrl_Gen_Cam.HideRigInOutliner" "Loc_Cam_UpShape.hio";
connectAttr "pck_Loc_Cam_opm.tmat" "Loc_Cam.opm";
connectAttr "Ctrl_Gen_Cam.HideRigInOutliner" "Loc_Cam.hio";
connectAttr "Ctrl_Gen_Cam.HideRigInOutliner" "Loc_CamShape.hio";
connectAttr "mmx_Cam_opm.o" "pck_Cam_opm.imat";
connectAttr "Ctrl_Adjust_Cam.wm" "mmx_Cam_opm.i[1]";
connectAttr "Flux_Cam_Rig.wim" "mmx_Cam_opm.i[2]";
connectAttr "Ctrl_Setting_Cam.Roll" "unitConversion1.i";
connectAttr "Ctrl_Setting_Cam.Shutter_Angle" "unitConversion2.i";
connectAttr "Ctrl_Gen_Cam.Cam_Lock_Selection" "Remap_Lock_Cam.i";
connectAttr "mmx_Ctrl_Aim_Cam_local1.o" "dcm_Ctrl_Aim_Cam_dir1.imat";
connectAttr "aim_Ctrl_Aim_Cam_mtx1.tmat" "mmx_Ctrl_Aim_Cam_local1.i[0]";
connectAttr "Ctrl_Adjust_Cam.wim" "mmx_Ctrl_Aim_Cam_local1.i[1]";
connectAttr "mmx_Ctrl_Aim_Cam_aimIn1.o" "aim_Ctrl_Aim_Cam_mtx1.imat";
connectAttr "Ctrl_Adjust_Cam.wm" "aim_Ctrl_Aim_Cam_mtx1.pmat";
connectAttr "cmp_Ctrl_Aim_Cam_aimT.omat" "mmx_Ctrl_Aim_Cam_aimIn1.i[1]";
connectAttr "Ctrl_Aim_Cam.opm" "mmx_Ctrl_Aim_Cam_aimIn1.i[2]";
connectAttr "Ctrl_Adjust_Cam.wm" "mmx_Ctrl_Aim_Cam_aimIn1.i[3]";
connectAttr "Ctrl_Aim_Cam.t" "cmp_Ctrl_Aim_Cam_aimT.it";
connectAttr "mmx_Ctrl_Up_Cam_local1.o" "dcm_Ctrl_Up_Cam_dir1.imat";
connectAttr "aim_Ctrl_Up_Cam_mtx1.tmat" "mmx_Ctrl_Up_Cam_local1.i[0]";
connectAttr "Ctrl_Adjust_Cam.wim" "mmx_Ctrl_Up_Cam_local1.i[1]";
connectAttr "mmx_Ctrl_Up_Cam_aimIn1.o" "aim_Ctrl_Up_Cam_mtx1.imat";
connectAttr "Ctrl_Adjust_Cam.wm" "aim_Ctrl_Up_Cam_mtx1.pmat";
connectAttr "cmp_Ctrl_Up_Cam_aimT.omat" "mmx_Ctrl_Up_Cam_aimIn1.i[1]";
connectAttr "Ctrl_Up_Cam.opm" "mmx_Ctrl_Up_Cam_aimIn1.i[2]";
connectAttr "Ctrl_Adjust_Cam.wm" "mmx_Ctrl_Up_Cam_aimIn1.i[3]";
connectAttr "Ctrl_Up_Cam.t" "cmp_Ctrl_Up_Cam_aimT.it";
connectAttr "mmx_Loc_Cam_Aim_local1.o" "pck_Loc_Cam_Aim_opm.imat";
connectAttr "Ctrl_Aim_Cam.wm" "mmx_Loc_Cam_Aim_local1.i[0]";
connectAttr "Cam_Guides.wim" "mmx_Loc_Cam_Aim_local1.i[1]";
connectAttr "mmx_camera1_up_local.o" "pck_camera1_up_opm.imat";
connectAttr "Ctrl_Up_Cam.wm" "mmx_camera1_up_local.i[0]";
connectAttr "Cam_Guides.wim" "mmx_camera1_up_local.i[1]";
connectAttr "mmx_Loc_Cam_local.o" "pck_Loc_Cam_opm.imat";
connectAttr "Ctrl_Adjust_Cam.wm" "mmx_Loc_Cam_local.i[0]";
connectAttr "Cam_Guides.wim" "mmx_Loc_Cam_local.i[1]";
connectAttr "Remap_Lock_Cam.msg" ":defaultRenderUtilityList1.u" -na;
// End of flux_cam_rig.ma
