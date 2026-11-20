# First-fleet test keepers

The portable cases below run in `skills/install/tests/test_first_fleet.py`.
The original OpenWiz readers still exercise their pinned release.
Fixtures and harness paths moved. All 33 case assertions are unchanged.

| OpenWiz case | Keeper |
| --- | --- |
| `RecordedJourney.test_the_conversation_follows_the_packaged_skill` | `RecordedJourney.test_the_conversation_follows_the_packaged_skill` in WizSkills. |
| `RecordedJourney.test_every_effect_follows_its_yes_and_every_choice_is_the_users_once` | `RecordedJourney.test_every_effect_follows_its_yes_and_every_choice_is_the_users_once` in WizSkills. |
| `RecordedJourney.test_the_plan_is_this_grills_small_first_fleet` | `RecordedJourney.test_the_plan_is_this_grills_small_first_fleet` in WizSkills. |
| `Continuation.test_only_current_verified_setup_and_a_brain_are_carried` | `Continuation.test_only_current_verified_setup_and_a_brain_are_carried` in WizSkills. |
| `Continuation.test_both_identities_carry_the_same_repository_brain_and_settings` | `Continuation.test_both_identities_carry_the_same_repository_brain_and_settings` in WizSkills. |
| `Continuation.test_the_carried_repository_is_the_only_one` | `Continuation.test_the_carried_repository_is_the_only_one` in WizSkills. |
| `Continuation.test_a_failed_refresh_withdraws_the_carried_setup_but_keeps_the_choices` | `Continuation.test_a_failed_refresh_withdraws_the_carried_setup_but_keeps_the_choices` in WizSkills. |
| `Continuation.test_a_companion_brain_reaches_decisions_only_through_its_configured_pair` | `Continuation.test_a_companion_brain_reaches_decisions_only_through_its_configured_pair` in WizSkills. |
| `Continuation.test_the_decisions_pair_is_written_once_and_only_on_yes` | `Continuation.test_the_decisions_pair_is_written_once_and_only_on_yes` in WizSkills. |
| `Continuation.test_a_decisions_write_cut_short_before_its_replace_can_be_confirmed_again` | `Continuation.test_a_decisions_write_cut_short_before_its_replace_can_be_confirmed_again` in WizSkills. |
| `Continuation.test_the_prepared_agents_are_reused_only_when_offered` | `Continuation.test_the_prepared_agents_are_reused_only_when_offered` in WizSkills. |
| `Launch.test_the_whole_journey_starts_one_fleet_thread_through_launch_fleet` | `Launch.test_the_whole_journey_starts_one_fleet_thread_through_launch_fleet` in WizSkills. |
| `Launch.test_repeat_and_reload_never_start_again` | `Launch.test_repeat_and_reload_never_start_again` in WizSkills. |
| `Launch.test_an_uncertain_start_is_never_retried_and_settles_only_on_its_record` | `Launch.test_an_uncertain_start_is_never_retried_and_settles_only_on_its_record` in WizSkills. |
| `Launch.test_uncertain_launch_accepts_only_configured_record_authors` | `Launch.test_uncertain_launch_accepts_only_configured_record_authors` in WizSkills. |
| `Launch.test_a_start_cut_short_before_its_outcome_settles_on_its_record` | `Launch.test_a_start_cut_short_before_its_outcome_settles_on_its_record` in WizSkills. |
| `Launch.test_a_start_that_could_not_run_is_refused_and_previewed_again` | `Launch.test_a_start_that_could_not_run_is_refused_and_previewed_again` in WizSkills. |
| `Launch.test_a_preview_is_void_once_setup_no_longer_verifies` | `Launch.test_a_preview_is_void_once_setup_no_longer_verifies` in WizSkills. |
| `Launch.test_missing_or_stale_approval_starts_nothing` | `Launch.test_missing_or_stale_approval_starts_nothing` in WizSkills. |
| `Launch.test_another_specs_frontier_is_not_this_fleets` | `Launch.test_another_specs_frontier_is_not_this_fleets` in WizSkills. |
| `Launch.test_the_yes_binds_the_preview_the_user_saw` | `Launch.test_the_yes_binds_the_preview_the_user_saw` in WizSkills. |
| `Launch.test_every_builder_profile_the_fleet_can_use_is_the_users_choice` | `Launch.test_every_builder_profile_the_fleet_can_use_is_the_users_choice` in WizSkills. |
| `Launch.test_without_carried_setup_local_agents_or_another_spec_nothing_starts` | `Launch.test_without_carried_setup_local_agents_or_another_spec_nothing_starts` in WizSkills. |
| `Launch.test_another_repository_never_runs_this_onboardings_launch` | `Launch.test_another_repository_never_runs_this_onboardings_launch` in WizSkills. |
| `Launch.test_the_demo_repository_is_created_once_and_read_back` | `Launch.test_the_demo_repository_is_created_once_and_read_back` in WizSkills. |
| `Launch.test_a_lost_create_is_read_before_any_retry` | `Launch.test_a_lost_create_is_read_before_any_retry` in WizSkills. |
| `Launch.test_an_existing_or_public_repository_is_never_taken_as_the_demo` | `Launch.test_an_existing_or_public_repository_is_never_taken_as_the_demo` in WizSkills. |
| `Launch.test_a_busy_state_file_is_refused` | `Launch.test_a_busy_state_file_is_refused` in WizSkills. |
| `DemoToInit.test_signed_out_demo_creation_refuses_with_a_sign_in_pointer` | `DemoRepository.test_signed_out_demo_creation_refuses_with_a_sign_in_pointer` in WizSkills. |
| `DemoToInit.test_a_created_demo_carries_on_into_init_s_brain_proposal` | Same OpenWiz case. It exercises the actual installed init command, which ships with OpenWiz. |
| `DemoToInit.test_the_preview_discloses_the_initial_commit_and_writes_nothing` | `DemoRepository.test_the_preview_discloses_the_initial_commit_and_writes_nothing` in WizSkills. |
| `DemoToInit.test_an_unread_or_missing_default_branch_is_never_created` | `DemoRepository.test_an_unread_or_missing_default_branch_is_never_created` in WizSkills. |
| `DemoToInit.test_its_own_repository_without_a_default_branch_stays_unresolved` | `DemoRepository.test_its_own_repository_without_a_default_branch_stays_unresolved` in WizSkills. |
| `DemoToInit.test_existing_repositories_and_owner_work_are_never_written` | `DemoRepository.test_existing_repositories_and_owner_work_are_never_written` in WizSkills. |
