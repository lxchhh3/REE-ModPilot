# Restructure M6: where the deleted tests' intents live now

The restructure plan (kevin, 2026-10-19) deletes the legacy mocked unit tests (`ModPilot/tests/unit`)
only once this table shows each file's intent covered by a test that runs real code, or belonging
to a feature M6 deletes. Written 2026-10-20 (M6), against fork branch `restructure`.

- **T1**: `ModPilot/tests/bl`, run in headless Blender 5.2.2 (`python -m modpilot_host.bpytest`).
- **T0**: `ModPilot/tests/core`, plain Python.
- **L0/L3**: tools-5.2 (`tests/test_l0_*.py`, `tests/test_l3_*.py`); since M5 its L3 replays call
  the steps (`modpilot.call`) inside headless Blender.

Most legacy tests asserted on the Python source a tool generated and the order of its calls to a mocked
`BlenderClient`. Those assertions have no counterpart: the steps are code, not generated text.
Where a legacy test pinned a *silent* behaviour that the restructure made loud on purpose, the
row says so. Those are design changes, recorded in each step module's docstring.

## Tool tests

| Legacy file | What it checked | Covered now by |
|---|---|---|
| `test_batch_export.py` | params (armor id / variant / parts / collections / natives root) | T1 `test_export.py::test_bad_export_params_fail_before_exporting`; T0 `test_params.py` |
| | scene validation (missing collection, armature) | T1 `test_export.py::test_bad_export_params_fail_before_exporting` |
| | scene binding: keys, default armor scheme, BoneSystem, fbxskel name | T1 `test_export.py::test_the_body_part_exports_with_its_colliders_and_bone_system`, `test_collections_come_from_the_scene_config_when_not_given` |
| | all 5 parts cleared, unselected parts not bound | T1 `test_export.py::test_bindings_of_parts_not_exported_are_cleared` (added in M6) |
| | export CANCELLED / exception / no output fails | T1 `test_export.py::test_a_file_the_exporter_fails_on_fails_the_step`, `test_an_export_that_writes_nothing_fails_the_step`, `test_a_failed_bone_system_export_fails_the_step` |
| | result names the exported parts | T1 `test_export.py::test_the_body_part_exports_with_its_colliders_and_bone_system` |
| | LLM tool schema; 2-minute socket timeout | deleted (no LLM tool schemas; no socket in a step) |
| `test_export_clsp.py` | the imported clsp collection is bound; blank without one; explicit choice; unknown one fails | T1 `test_export.py::test_the_body_part_exports_with_its_colliders_and_bone_system`, `test_an_empty_clsp_collection_exports_a_blank_clsp`, `test_bad_export_params_fail_before_exporting` |
| `test_mesh_cleanup.py` | the four cleanup operators run before export | T1 `test_export.py::test_the_body_part_exports...` (`meshes_cleaned`, smoothing); the built-in fallback is gone on purpose (M2.7: no silent fallback) and `MeshCleanup` was never registered |
| `test_clsp_bits_match_file.py` | the body-bit catalog is the bundled clsp's layout, incl. the wide hip sphere | T0 `test_colliders_catalog.py`; T1 `test_colliders.py::test_apply_checks_every_entry_before_writing_any` |
| `test_physics_colliders.py` | bit catalog and helpers | T0 `test_colliders_catalog.py` |
| | collider_create binds to the MH Wilds armature, explicit armature wins, a missing one fails | T1 `test_colliders.py::test_create_binds_every_collider_to_a_bone_of_the_target_armature`, `test_create_needs_an_armature` |
| | collider_apply flag forms, range / type checks | T1 `test_colliders.py::test_apply_writes_both_flag_forms`, `test_apply_checks_every_entry_before_writing_any` |
| | an unknown chain group is only a warning | changed on purpose: every entry is checked first and an unknown group fails (`test_apply_checks_every_entry_before_writing_any`) |
| `test_end_bones.py` | weighted leaves get `_End` bones after smart_graft | T1 `test_physics.py::test_every_weighted_leaf_gets_its_end_bone_after_the_join`; L3 `test_l3_fixes.py` |
| `test_join_prep.py` | every part's key mix baked, UV / colour layers made join-safe | T1 `test_vertex_groups.py::test_every_part_ships_as_it_looked_and_keeps_its_keys`, `test_uv_layers_match_by_position_and_colourless_parts_are_white`; L3 `test_l3_fixes.py` |
| `test_source_fixes.py` | rigid garments skinned, MochiFitter `_MFBase` bones folded | T1 `test_setup.py::test_a_garment_hung_on_a_bone_becomes_skinned_to_it_in_place`, `test_mochifitter_helper_bones_fold_into_the_bones_they_copy` |
| `test_shared_chain_settings.py` | SHARED mode: one settings object per type, heads read as RE Chain Editor does | T1 `test_physics.py::test_shared_settings_give_each_type_its_own_object` |
| `test_physics_bones.py` | presets JSON and helpers | T0 `test_physics_presets.py` |
| | transplant / classification params and results | T1 `test_physics.py::test_every_weighted_leaf...`, `test_classification_lists_the_chain_heads`, `test_bad_chain_params_fail_before_touching_the_scene` |
| | prepare_only, merge with `_End` cascade, header calibration, angle ramp | T1 `test_physics.py::test_prepare_only_refreshes_the_marks_and_says_so`, `test_merged_bones_take_their_end_leaves_with_them`, `test_the_chain_header_gets_the_mh_wilds_calibration...`, `test_the_angle_limits_ramp_down_each_chain` |
| | bones_to_clear runs and clears | T1 `test_physics.py::test_cleared_bones_lose_their_chain_mark_and_get_no_chain` (added in M6) |
| | SEPARATE params by chain head; untyped / disagreeing heads left alone | T1 `test_physics.py::test_separate_settings_take_each_heads_type_and_leave_untyped_ones_alone` |
| | verify chain marks (heads without `_End`) | T1 `test_physics.py::test_prepare_only_refreshes_the_marks_and_says_so` (`marks_without_end`) |
| | "non-fatal" cascade failure, header tune swallowing exceptions, consolidation fallback | changed on purpose: these fail the step now (no silent paths) |
| `test_phases.py` | pose_correction: pose cleared, scale align, Y shift, skip flag, presets | T1 `test_pose_skeleton.py` (first seven tests) |
| | MMD → `mmd_a_to_tpose`, Endfield → `apply_transform_forward` + the pose record | T1 `test_pose_skeleton.py::test_mmd_and_endfield_rigs_get_their_t_pose_conversion`: **strict xfail**. The Toolkit's conversion calls `select_grouped`, whose poll fails headless; the legacy test only checked the generated code named the operator. Open finding, 2026-10-20 |
| | skeleton_align | T1 `test_pose_skeleton.py::test_skeleton_align_snaps_and_reports_what_it_unhid`, `test_skeleton_align_needs_both_armatures` |
| | vertex_groups: prep, convert, re-parent, MMD cleanup, normalise | T1 `test_vertex_groups.py` (all eight) |
| `test_infer_model_type.py` | exact / supplement / custom / unsupported decisions, forced preset, force_custom, missing armature / Toolkit / presets | T0 `test_presets.py::test_the_decision_thresholds` and the coverage tests; T1 `test_setup.py` (inference tests) |
| `test_preset_catalog.py` | X-preset enumeration, coverage, best pick, fuzzy match, preset folder discovery | T0 `test_presets.py`; T1 `test_setup.py::test_a_supplemented_preset_lands_in_the_toolkit_and_is_inferred_next` |
| `test_preset_write.py` | supplement / custom writers and their refusals | T0 `test_presets.py` (writer tests); T1 `test_setup.py::test_a_supplemented_preset...`, `test_a_custom_preset_lands_in_the_toolkit` |
| `test_setup_import_source.py` | FBX import, already-imported, refusals, CANCELLED | T1 `test_setup.py::test_an_fbx_is_imported_and_its_armature_reported`, `test_an_armature_already_in_the_scene_is_used_as_it_is`, `test_import_refusals`; `test_call.py::test_an_operator_that_cancels_is_an_operator_error` (added in M6) |
| `test_toolkit_285_contract.py` | Toolkit 2.8.5 preset stems; physics switches the X preset to mhws; bundled clsp imported through `re_clsp.importfile` | L0 `test_l0_preset_values.py` (reads `src/modpilot` since M5); T1 `test_physics.py::test_every_weighted_leaf...` (`import_preset_enum == "mhws.json"`), `test_colliders.py::test_create_binds...`; L0 `test_l0_modpilot_ops.py` |
| `test_emission_socket.py` | the emission socket is found by its Blender 4 name, in setup and inspect | T1 `test_materials.py::test_base_colour_and_emission_are_wired_and_reported`, `test_inspect_traces_each_wired_slot_back_to_its_image` |
| `test_material.py` | material_setup: presets, normal wiring per preset, null slots, refusals | T1 `test_materials.py` (setup tests) |
| | material_inspect: params, texture scan by extension, connections | T1 `test_materials.py` (inspect tests) |
| | material_generate: params, collection, presets, auto-guessed, failures | T1 `test_materials.py` (generate tests) |
| | the "skipped slots" result | changed on purpose: a bad mapping changes nothing and fails (`test_a_bad_mapping_changes_nothing`) |
| | slot-token / LLM suggestion / reverse inference / UV-overlap vision merges | deleted with the LLM and vision helpers |
| `test_query_tools.py` | the ten queries' results and errors | T1 `test_query.py` (all); `test_get_object_props` checks the `_` keys are left out (added in M6) |
| | query tools registered in the agent loop | deleted with the agent loop |
| `test_data_dir.py` | the catalogs have one copy, `src/modpilot/data` | T0 `test_physics_presets.py`, `test_colliders_catalog.py` read it; `app/` (the other reader) is gone |

## Tests of deleted features

| Legacy file | Feature (deleted in M6) |
|---|---|
| `test_agent_interrupt.py`, `test_agent_loop.py`, `test_agent_loop_events.py`, `test_agent_loop_history.py`, `test_context_management_flow.py`, `test_history.py`, `test_phase_transition.py` | ModPilot's own agent loop (Claude Code is the agent since 2026-10-12) |
| `test_llm_client.py`, `test_ollama_provider.py`, `test_vision_client.py` | LLM and vision providers |
| `test_app_config.py`, `test_session_config_form.py`, `test_sse_routes.py`, `test_widget_routes.py`, `test_toolkit_status_route.py`, `test_viewport_screenshot.py`, `test_infer_model_type_routing.py` | the FastAPI app, its routes and the React UI's events |
| `test_blender_client.py` | the legacy socket client; its replacement `modpilot_host.transport` is T0 `test_transport.py` |
| `test_toolkit_probe.py` | replaced by the `doctor` step: T1 `test_m1_steps.py::test_doctor_*` |
| `test_bridge_adapter.py` | the M1–M5 strangler adapter `app/phases/_bridge.py` |

## Other test folders removed

- `tests/diff`: T2, the legacy tool against the new step. It needs `app/`, and its job ended when the
  last tool was ported (f00f8e1).
- `tests/e2e`, `scripts/record_*_walkthrough.py`: Playwright drives and recordings of the React UI.
- `tests/integration`: empty.
