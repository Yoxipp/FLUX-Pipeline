# CONTEXT — Folder Manager

> Domain: backend
> Path: backend/features/folder_manager/
> Last updated: 2026-05-13
> Key internal dependencies: core.paths, core.constants, core.json_manager

## 1. Module Role

Creates and validates folder hierarchies for FLUX projects, assets, and shots. Manages the tokens.json registry that maps logical token keys (CLASS, TYPE, NAME, SEQ, SHOT) to relative filesystem paths. Central authority for naming conventions and path resolution.

## 2. When to Read This Module

When creating new projects/assets/shots, validating filenames, parsing or formatting token values, resolving paths from tokens, or managing the tokens registry. Also read when implementing filename-based routing in publish/import pipelines.

## 3. Files Present

| File | Type | Role | Public Exports / Elements |
|---|---|---|---|
| `project_init.py` | module | Create new projects with standard folder tree and tokens.json | `create_project(project_name, projects_root?)`, `project_exists(project_name, projects_root?)`, `list_projects(projects_root?)` |
| `asset_creator.py` | module | Create asset folders and register NAME tokens | `create_asset(project_path, class_token, asset_name)`, `asset_exists(project_path, class_token, asset_name)`, `list_assets(project_path, class_token?)` |
| `seq_shot_creator.py` | module | Create sequence/shot folders and register SEQ/SHOT tokens | `create_sequence(project_path, seq_number, padding?)`, `create_shot(project_path, seq_number, shot_number, padding?)`, `list_sequences(project_path)`, `list_shots(project_path, seq_number?, padding?)`, `sequence_exists(...)`, `shot_exists(...)` |
| `naming_validator.py` | module | Token parsing, filename validation, and formatting | `parse_filename(filename)`, `validate_token(value)`, `format_token(raw)`, `format_seq(number, padding?)`, `format_shot(number, padding?)`, `format_version(number, padding?)`, `get_base_name(filename)`, `strip_version(filename)`, `build_asset_filename(...)`, `build_shot_filename(...)`, `validate_filename(filename)` |
| `tokens.py` | module | Load/save/query tokens.json (project token registry) | `load_tokens(project_path)`, `save_tokens(project_path, tokens)`, `add_token(project_path, token_type, token_value, rel_path)`, `remove_token(project_path, token_type, token_value)`, `get_path_for_token(tokens, token_type, token_value)`, `resolve_path(project_path, tokens, token_type, token_value)`, `get_all_tokens(project_path)`, `build_default_tokens()` |

## 4. Useful Relations

- **Consumed by**: publisher (resolve_publish_path), importer (file_browser), asset/project creation UI endpoints
- **Reads**: tokens.json per project, filesystem folder structures
- **Writes**: tokens.json (atomic JSON writes), creates disk folders via core.paths.ensure_dir
- **Depends on**: core.constants (DEFAULT_PADDING, DEFAULT_INSTANCE, DEFAULT_CLASS_TOKENS, JSON_TOKENS)

## 5. Module Entry Points

1. **New project**: `create_project("MY_PROJECT")` → scaffolds all standard folders + tokens.json.
2. **New asset**: `create_asset(project_path, "CHAR", "mychar")` → creates CHAR/MYCHAR/ with class-specific subdirs + registers NAME token.
3. **New sequence/shot**: `create_sequence(project, 1)` then `create_shot(project, 1, 1)` → registers SEQ/SHOT tokens.
4. **Filename parsing**: `parse_filename("CHAR_RIG_HERO_A_LAST.mb")` → dict with CLASS/TYPE/NAME/INSTANCE/ITER/is_shot.
5. **Token to path**: `resolve_path(project, tokens, "NAME", "MYCHAR")` → absolute filesystem path.

## 6. Per-File Detail

### `project_init.py`

**Role:** One-time project scaffolding with 11 standard folders and default tokens.

#### `create_project(project_name, projects_root?)`
Create project under DOSSIER_PROJETS with formatted name (uppercase, clean). Returns project Path. Raises FileExistsError/ValueError.
→ used by: /api/projects/create endpoint

#### `project_exists(project_name, projects_root?)`
Check if project name exists (formatted). Returns bool.
→ used by: validation before create, project dropdown UI

#### `list_projects(projects_root?)`
Return sorted list of project names under projects_root (excludes hidden dirs).
→ used by: project browser, sidebar menu

### `asset_creator.py`

**Role:** Asset folder creation with class-specific subdirectories. Registers NAME tokens.

#### `create_asset(project_path, class_token, asset_name)`
Create asset folder with subdirs (model/shading/rig per class). Adds NAME token. Raises ValueError/FileExistsError.
→ used by: asset creation UI modal

#### `asset_exists(project_path, class_token, asset_name)`
Check if asset folder exists. Returns bool.
→ used by: validation, duplicate detection

#### `list_assets(project_path, class_token?)`
Return sorted asset names under project. If class_token given, filter to that class only.
→ used by: asset browser tree, publish destination picker

### `seq_shot_creator.py`

**Role:** Shot folder hierarchy (SEQ###/SHOT###/) with anim phases and standard subfolders.

#### `create_sequence(project_path, seq_number, padding?)`
Create /shot/SEQ###/ folder. Registers SEQ token. Raises FileExistsError.
→ used by: shot setup wizard (often auto-created by create_shot)

#### `create_shot(project_path, seq_number, shot_number, padding?)`
Create /shot/SEQ###/SHOT###/ with layout/fx/cfx/anim subfolders. Auto-creates parent sequence. Registers SHOT token.
→ used by: shot creation UI

#### `list_sequences(project_path)`
Return sorted SEQ token keys from tokens.json.
→ used by: sequence browser, shot hierarchy UI

#### `list_shots(project_path, seq_number?, padding?)`
Return sorted SHOT token keys, optionally filtered by sequence.
→ used by: shot browser under sequence, shot selector in render UI

### `naming_validator.py`

**Role:** Central validator for Flux naming convention (CLASS_TYPE_NAME_INSTANCE_ITER[.ext] or CLASS_SEQ###_SHOT###_INSTANCE_ITER[.ext]).

#### `parse_filename(filename)`
Return dict with CLASS/TYPE/NAME/INSTANCE/ITER/extension/is_shot, or None if unparseable.
→ used by: publish pipeline (determine destination), file filters, metadata extraction

#### `validate_token(value)`
Return error message if token invalid (empty, forbidden chars, not uppercase), else None.
→ used by: project/asset name validation, form error display

#### `format_token(raw)`
Normalize string → uppercase, strip accents, replace spaces with underscores, remove forbidden chars.
→ used by: all token inputs (project names, asset names, custom tokens)

#### `validate_filename(filename)`
Return error message if filename unparseable, else None.
→ used by: file upload validation, publish source check

#### `get_base_name(filename)`
Return CLASS_TYPE_NAME_instance (strip version and extension).
→ used by: version resolver (find related files), modif_log grouping

#### `strip_version(filename)`
Return filename without _vXXX or _LAST suffix. Keeps extension.
→ used by: UI display, version history comparison

#### `format_seq(number, padding?), format_shot(number, padding?), format_version(number, padding?)`
Return properly formatted SEQ/SHOT/version strings (SEQ001, SHOT001, v001).
→ used by: folder creation, filename building, display in UI

#### `build_asset_filename(class, type, name, instance?, version?, extension?)`
Return properly formatted asset filename.
→ used by: export scripts, file naming conventions

#### `build_shot_filename(class, seq, shot, instance?, version?, extension?)`
Return properly formatted shot filename.
→ used by: export scripts, shot file naming

### `tokens.py`

**Role:** Load, save, and query tokens.json. Single source of truth for token→path resolution.

#### `load_tokens(project_path)`
Load tokens.json, fallback to defaults if missing/invalid. Ensures all sections exist.
→ used by: any path resolution (publisher, importer, asset browser)

#### `save_tokens(project_path, tokens)`
Write tokens dict to tokens.json atomically. Returns bool.
→ used by: add_token, remove_token, internal mutations

#### `add_token(project_path, token_type, token_value, rel_path)`
Add/update token entry in tokens.json. *token_type*: CLASS/TYPE/NAME/SEQ/SHOT/custom. Returns bool.
→ used by: asset_creator, seq_shot_creator after folder creation

#### `remove_token(project_path, token_type, token_value)`
Remove token entry. Returns True if it existed.
→ used by: asset/shot deletion (future cleanup)

#### `get_path_for_token(tokens, token_type, token_value)`
Query: return relative path for token value, or None.
→ used by: path resolution logic (publish_core, file_browser)

#### `resolve_path(project_path, tokens, token_type, token_value)`
Query: return absolute path for token (joins project_path + relative).
→ used by: UI navigation, file picker defaults

#### `get_all_tokens(project_path)`
Return deep copy of full tokens dict (safe for caller mutation).
→ used by: API endpoints that serialize tokens, token browser UI

#### `build_default_tokens()`
Return fresh tokens dict with default CLASS entries (CHAR, PROPS, ENV, CFXRIG, FXRIG).
→ used by: project_init, tokens.json bootstrapping

## 7. Maintenance Notes

- **Default CLASS tokens**: Defined in core.constants.DEFAULT_CLASS_TOKENS; class subtypes (model/shading/rig) are auto-created by asset_creator.
- **Version padding**: DEFAULT_PADDING=3 (v001, v002) unless overridden.
- **Forward slash paths**: All rel_path in tokens.json use "/" not "\\"; join with project_path via Path / operator.
- **Naming edge cases**: Hyphens and spaces → underscores; accents stripped (café → CAFE); consecutive underscores collapsed.
- **Shot token keys**: Stored as "SEQ001/SHOT001" (composite) to scope shots under sequences in tokens.json.
- **Custom tokens**: Tokens.json allows "custom" section for pipeline-specific keys beyond standard CLASS/TYPE/NAME/SEQ/SHOT.
