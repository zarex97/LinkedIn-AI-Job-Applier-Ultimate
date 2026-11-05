"""Tests for src/job_manager/linkedin/search_customizer_linkedin.py"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.job_manager.linkedin.search_customizer_linkedin import SearchCustomizer

MODULE = "src.job_manager.linkedin.search_customizer_linkedin"


@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.keyboard = AsyncMock()
    return page


@pytest.fixture
def customizer(mock_page):
    sc = SearchCustomizer(mock_page)
    sc.set_advanced_search_params(
        {
            "positions": ["Software Engineer", "Python Developer"],
            "locations": ["Germany"],
            "remote": True,
            "hybrid": True,
            "onsite": False,
            "experience_level": {"entry": True, "mid_senior_level": True, "director": False},
            "job_types": {"full_time": True, "contract": False, "internship": True},
            "date": {"24_hours": True, "week": False},
            "apply_once_at_company": True,
            "company_blacklist": ["Wayfair", "Crossover"],
            "title_blacklist": ["word1", "word2"],
            "location_blacklist": ["Brazil"],
        }
    )
    return sc


# ---------------------------------------------------------------------------
# set_advanced_search_params / is_job_blacklisted (base class, exercised here)
# ---------------------------------------------------------------------------


class TestSetAdvancedSearchParams:
    def test_sets_positions_and_locations(self, customizer):
        assert customizer.positions == ["Software Engineer", "Python Developer"]
        assert customizer.locations == ["Germany"]

    def test_sets_work_location_flags(self, customizer):
        assert customizer.remote is True
        assert customizer.hybrid is True
        assert customizer.onsite is False

    def test_sets_experience_level(self, customizer):
        assert customizer.experience_level["entry"] is True
        assert customizer.experience_level["director"] is False

    def test_sets_job_types(self, customizer):
        assert customizer.job_types["full_time"] is True
        assert customizer.job_types["contract"] is False

    def test_sets_date_posted(self, customizer):
        assert customizer.date_posted["24_hours"] is True
        assert customizer.date_posted["week"] is False

    def test_sets_blacklists(self, customizer):
        assert "Wayfair" in customizer.company_blacklist
        assert "word1" in customizer.title_blacklist
        assert "Brazil" in customizer.location_blacklist


class TestSearchDebugHelpers:
    def test_format_linkedin_keyword_query_quotes_and_ors_positions(self, mock_page):
        sc = SearchCustomizer(mock_page)
        sc.positions = ["CTO", "Chief Technology Officer", " Technical Manager ", ""]
        assert (
            sc.format_linkedin_keyword_query()
            == '"CTO" OR "Chief Technology Officer" OR "Technical Manager"'
        )


class TestIsJobBlacklisted:
    def test_blacklisted_company(self, customizer):
        assert customizer.is_job_blacklisted("Engineer", "Wayfair", "Germany") is True

    def test_blacklisted_company_case_insensitive(self, customizer):
        assert customizer.is_job_blacklisted("Engineer", "wayfair", "Germany") is True

    def test_blacklisted_title(self, customizer):
        assert customizer.is_job_blacklisted("word1 Developer", "Google", "Germany") is True

    def test_blacklisted_location(self, customizer):
        assert customizer.is_job_blacklisted("Engineer", "Google", "Brazil") is True

    def test_not_blacklisted(self, customizer):
        assert customizer.is_job_blacklisted("Data Scientist", "Amazon", "Germany") is False

    def test_partial_title_match(self, customizer):
        assert customizer.is_job_blacklisted("Senior word2 Engineer", "Amazon", "Germany") is True


# ---------------------------------------------------------------------------
# _set_basic_search_terms
# ---------------------------------------------------------------------------


class TestSetBasicSearchTerms:
    @pytest.mark.asyncio
    async def test_fills_keywords_with_boolean_or_query(self, customizer):
        with (
            patch(f"{MODULE}.safe_fill", new_callable=AsyncMock, return_value=True) as mock_fill,
            patch(f"{MODULE}.find_element_safely", new_callable=AsyncMock, return_value=None),
        ):
            await customizer._set_basic_search_terms()

        first_call_args = mock_fill.call_args_list[0]
        assert '"Software Engineer" OR "Python Developer"' in first_call_args[0]

    @pytest.mark.asyncio
    async def test_fills_location_and_presses_enter(self, customizer, mock_page):
        mock_element = AsyncMock()

        def fill_side_effect(page, selector, value, **kwargs):
            if "zip code" in selector or "City" in selector or "location" in selector:
                return True
            return True

        with (
            patch(f"{MODULE}.safe_fill", new_callable=AsyncMock, side_effect=fill_side_effect),
            patch(
                f"{MODULE}.find_element_safely",
                new_callable=AsyncMock,
                return_value=mock_element,
            ),
        ):
            await customizer._set_basic_search_terms()

        mock_page.keyboard.press.assert_called_once_with("Enter")

    @pytest.mark.asyncio
    async def test_logs_warning_when_keywords_not_filled(self, customizer):
        with (
            patch(f"{MODULE}.safe_fill", new_callable=AsyncMock, return_value=False),
            patch(f"{MODULE}.find_element_safely", new_callable=AsyncMock, return_value=None),
        ):
            await customizer._set_basic_search_terms()

    @pytest.mark.asyncio
    async def test_skips_keywords_when_no_positions(self, mock_page):
        sc = SearchCustomizer(mock_page)
        sc.positions = []
        sc.locations = ["Germany"]
        with (
            patch(f"{MODULE}.safe_fill", new_callable=AsyncMock, return_value=True) as mock_fill,
            patch(f"{MODULE}.find_element_safely", new_callable=AsyncMock, return_value=None),
        ):
            await sc._set_basic_search_terms()
        assert all("Software Engineer" not in str(call.args) for call in mock_fill.call_args_list)

    @pytest.mark.asyncio
    async def test_clears_location_when_no_locations_configured(self, mock_page):
        sc = SearchCustomizer(mock_page)
        sc.positions = []
        sc.locations = []
        sc._dismiss_location_typeahead = AsyncMock()

        with patch(f"{MODULE}.safe_fill", new_callable=AsyncMock, return_value=True) as mock_fill:
            await sc._set_basic_search_terms()

        mock_fill.assert_called_once()
        assert mock_fill.call_args.args[2] == ""
        mock_page.keyboard.press.assert_not_called()
        sc._dismiss_location_typeahead.assert_called_once()

    @pytest.mark.asyncio
    async def test_dismiss_location_typeahead_presses_escape_and_blurs(self, customizer, mock_page):
        with patch(f"{MODULE}.async_pause", new_callable=AsyncMock):
            await customizer._dismiss_location_typeahead()

        mock_page.keyboard.press.assert_called_once_with("Escape")
        mock_page.evaluate.assert_called_once_with(
            "document.activeElement && document.activeElement.blur()"
        )

    @pytest.mark.asyncio
    async def test_commit_basic_search_clicks_search_button(self, customizer):
        with (
            patch(f"{MODULE}.safe_click", new_callable=AsyncMock, return_value=True) as mock_click,
            patch(f"{MODULE}.async_pause", new_callable=AsyncMock),
        ):
            await customizer._commit_basic_search()

        mock_click.assert_called_once()

    @pytest.mark.asyncio
    async def test_commit_basic_search_falls_back_to_enter(self, customizer, mock_page):
        with (
            patch(f"{MODULE}.safe_click", new_callable=AsyncMock, return_value=False),
            patch(f"{MODULE}.async_pause", new_callable=AsyncMock),
        ):
            await customizer._commit_basic_search()

        mock_page.keyboard.press.assert_called_once_with("Enter")

    @pytest.mark.asyncio
    async def test_does_not_press_enter_when_no_location_element(self, customizer, mock_page):
        with (
            patch(f"{MODULE}.safe_fill", new_callable=AsyncMock, return_value=True),
            patch(f"{MODULE}.find_element_safely", new_callable=AsyncMock, return_value=None),
        ):
            await customizer._set_basic_search_terms()

        mock_page.keyboard.press.assert_not_called()


# ---------------------------------------------------------------------------
# _open_all_filters
# ---------------------------------------------------------------------------


class TestOpenAllFilters:
    @pytest.mark.asyncio
    async def test_returns_true_when_filter_button_found(self, customizer):
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, return_value=True):
            result = await customizer._open_all_filters()
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_button_found(self, customizer):
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, return_value=False):
            result = await customizer._open_all_filters()
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self, customizer):
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, side_effect=Exception("err")):
            result = await customizer._open_all_filters()
        assert result is False


# ---------------------------------------------------------------------------
# _set_date_posted_filter
# ---------------------------------------------------------------------------


class TestSetDatePostedFilter:
    @pytest.mark.asyncio
    async def test_clicks_correct_date_option(self, customizer):
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, return_value=True) as mock_click:
            await customizer._set_date_posted_filter()

        clicked_selectors = [str(call) for call in mock_click.call_args_list]
        assert any("24 hours" in s or "24_hours" in s for s in clicked_selectors)

    @pytest.mark.asyncio
    async def test_skips_when_date_posted_empty(self, mock_page):
        sc = SearchCustomizer(mock_page)
        sc.date_posted = {}
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock) as mock_click:
            await sc._set_date_posted_filter()
        mock_click.assert_not_called()

    @pytest.mark.asyncio
    async def test_only_clicks_enabled_date(self, customizer):
        customizer.date_posted = {"week": False, "month": True, "24_hours": False}
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, return_value=True) as mock_click:
            await customizer._set_date_posted_filter()

        clicked_selectors = [str(call) for call in mock_click.call_args_list]
        assert any("Past month" in s for s in clicked_selectors)

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self, customizer):
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, side_effect=Exception("err")):
            await customizer._set_date_posted_filter()


# ---------------------------------------------------------------------------
# _set_experience_level_filter
# ---------------------------------------------------------------------------


class TestSetExperienceLevelFilter:
    @pytest.mark.asyncio
    async def test_clicks_enabled_experience_levels(self, customizer):
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, return_value=True) as mock_click:
            await customizer._set_experience_level_filter()

        assert mock_click.call_count >= 2

    @pytest.mark.asyncio
    async def test_skips_disabled_experience_levels(self, customizer):
        customizer.experience_level = {"director": False, "executive": False}
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, return_value=True) as mock_click:
            await customizer._set_experience_level_filter()
        mock_click.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_experience_level_empty(self, mock_page):
        sc = SearchCustomizer(mock_page)
        sc.experience_level = {}
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock) as mock_click:
            await sc._set_experience_level_filter()
        mock_click.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self, customizer):
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, side_effect=Exception("err")):
            await customizer._set_experience_level_filter()


# ---------------------------------------------------------------------------
# _set_job_type_filter
# ---------------------------------------------------------------------------


class TestSetJobTypeFilter:
    @pytest.mark.asyncio
    async def test_clicks_enabled_job_types(self, customizer):
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, return_value=True) as mock_click:
            await customizer._set_job_type_filter()

        assert mock_click.call_count >= 1

    @pytest.mark.asyncio
    async def test_uses_element_number_1_for_internship(self, customizer):
        customizer.job_types = {"internship": True}
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, return_value=True) as mock_click:
            await customizer._set_job_type_filter()

        call_kwargs = mock_click.call_args_list[0][1]
        assert call_kwargs.get("element_number") == 1

    @pytest.mark.asyncio
    async def test_uses_element_number_0_for_non_internship(self, customizer):
        customizer.job_types = {"full_time": True}
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, return_value=True) as mock_click:
            await customizer._set_job_type_filter()

        call_kwargs = mock_click.call_args_list[0][1]
        assert call_kwargs.get("element_number") == 0

    @pytest.mark.asyncio
    async def test_skips_when_job_types_empty(self, mock_page):
        sc = SearchCustomizer(mock_page)
        sc.job_types = {}
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock) as mock_click:
            await sc._set_job_type_filter()
        mock_click.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self, customizer):
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, side_effect=Exception("err")):
            await customizer._set_job_type_filter()


# ---------------------------------------------------------------------------
# _set_work_location_filter
# ---------------------------------------------------------------------------


class TestSetWorkLocationFilter:
    @pytest.mark.asyncio
    async def test_clicks_remote_and_hybrid(self, customizer):
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, return_value=True) as mock_click:
            await customizer._set_work_location_filter()

        clicked_selectors = [str(call) for call in mock_click.call_args_list]
        assert any("Remote" in s for s in clicked_selectors)
        assert any("Hybrid" in s for s in clicked_selectors)

    @pytest.mark.asyncio
    async def test_does_not_click_onsite_when_disabled(self, customizer):
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, return_value=True) as mock_click:
            await customizer._set_work_location_filter()

        clicked_selectors = [str(call) for call in mock_click.call_args_list]
        assert not any("On-site" in s for s in clicked_selectors)

    @pytest.mark.asyncio
    async def test_no_clicks_when_all_disabled(self, mock_page):
        sc = SearchCustomizer(mock_page)
        sc.remote = False
        sc.hybrid = False
        sc.onsite = False
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock) as mock_click:
            await sc._set_work_location_filter()
        mock_click.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self, customizer):
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, side_effect=Exception("err")):
            await customizer._set_work_location_filter()


# ---------------------------------------------------------------------------
# _apply_filters
# ---------------------------------------------------------------------------


class TestApplyFilters:
    @pytest.mark.asyncio
    async def test_returns_true_when_apply_button_found(self, customizer):
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, return_value=True):
            result = await customizer._apply_filters()
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_apply_button(self, customizer):
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, return_value=False):
            result = await customizer._apply_filters()
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self, customizer):
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, side_effect=Exception("err")):
            result = await customizer._apply_filters()
        assert result is False

    @pytest.mark.asyncio
    async def test_only_targets_show_results_button(self, customizer):
        # A broad "contains Apply" match clicked LinkedIn's "Easy Apply" filter pill,
        # which silently limited every search to Easy Apply jobs.
        mock_click = AsyncMock(return_value=False)
        customizer.page.url = "https://www.linkedin.com/jobs/search/?keywords=x"
        with patch(f"{MODULE}.safe_click", mock_click):
            await customizer._apply_filters()
        selectors = [call.args[1] for call in mock_click.call_args_list]
        assert selectors
        for selector in selectors:
            assert "show results" in selector.lower().replace("-", " "), selector

    @pytest.mark.asyncio
    async def test_true_when_linkedin_already_applied_filters(self, customizer):
        customizer.page.url = "https://www.linkedin.com/jobs/search/?f_E=4&f_TPR=r2592000"
        with patch(f"{MODULE}.safe_click", new_callable=AsyncMock, return_value=False):
            result = await customizer._apply_filters()
        assert result is True


# ---------------------------------------------------------------------------
# _set_easy_apply_filter
# ---------------------------------------------------------------------------


class TestSetEasyApplyFilter:
    @pytest.mark.asyncio
    async def test_skips_when_easy_apply_only_mode_false(self, customizer):
        with (
            patch(f"{MODULE}.EASY_APPLY_ONLY_MODE", False),
            patch(f"{MODULE}.find_element_safely", new_callable=AsyncMock) as mock_find,
        ):
            await customizer._set_easy_apply_filter()
        mock_find.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_toggle_when_already_enabled(self, customizer):
        mock_input = AsyncMock()
        mock_input.get_attribute = AsyncMock(return_value="true")

        with (
            patch(f"{MODULE}.EASY_APPLY_ONLY_MODE", True),
            patch(f"{MODULE}.find_element_safely", new_callable=AsyncMock, return_value=mock_input),
            patch(f"{MODULE}.safe_click", new_callable=AsyncMock) as mock_click,
        ):
            await customizer._set_easy_apply_filter()

        mock_click.assert_not_called()

    @pytest.mark.asyncio
    async def test_toggles_when_not_enabled(self, customizer):
        mock_input = AsyncMock()
        mock_input.get_attribute = AsyncMock(return_value="false")

        with (
            patch(f"{MODULE}.EASY_APPLY_ONLY_MODE", True),
            patch(f"{MODULE}.find_element_safely", new_callable=AsyncMock, return_value=mock_input),
            patch(f"{MODULE}.safe_click", new_callable=AsyncMock, return_value=True) as mock_click,
        ):
            await customizer._set_easy_apply_filter()

        mock_click.assert_called()

    @pytest.mark.asyncio
    async def test_toggles_when_input_element_not_found(self, customizer):
        with (
            patch(f"{MODULE}.EASY_APPLY_ONLY_MODE", True),
            patch(f"{MODULE}.find_element_safely", new_callable=AsyncMock, return_value=None),
            patch(f"{MODULE}.safe_click", new_callable=AsyncMock, return_value=True) as mock_click,
        ):
            await customizer._set_easy_apply_filter()

        mock_click.assert_called()

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self, customizer):
        with (
            patch(f"{MODULE}.EASY_APPLY_ONLY_MODE", True),
            patch(
                f"{MODULE}.find_element_safely",
                new_callable=AsyncMock,
                side_effect=Exception("err"),
            ),
        ):
            await customizer._set_easy_apply_filter()


# ---------------------------------------------------------------------------
# set_search_params (orchestration)
# ---------------------------------------------------------------------------


class TestSetSearchParams:
    @pytest.mark.asyncio
    async def test_navigates_to_linkedin_jobs(self, customizer, mock_page):
        with (
            patch(f"{MODULE}.LINKEDIN_RECOMMENDED_JOBS_MODE", False),
            patch(f"{MODULE}.LINKEDIN_TOP_APPLICANT_JOBS_MODE", False),
            patch(f"{MODULE}.async_pause"),
            patch.object(customizer, "_set_basic_search_terms", new_callable=AsyncMock),
            patch.object(customizer, "_commit_basic_search", new_callable=AsyncMock),
            patch.object(
                customizer, "_open_all_filters", new_callable=AsyncMock, return_value=True
            ),
            patch.object(customizer, "_set_date_posted_filter", new_callable=AsyncMock),
            patch.object(customizer, "_set_experience_level_filter", new_callable=AsyncMock),
            patch.object(customizer, "_set_job_type_filter", new_callable=AsyncMock),
            patch.object(customizer, "_set_work_location_filter", new_callable=AsyncMock),
            patch.object(customizer, "_set_easy_apply_filter", new_callable=AsyncMock),
            patch.object(customizer, "_apply_filters", new_callable=AsyncMock, return_value=True),
        ):
            await customizer.set_search_params()

        mock_page.goto.assert_called_once_with(
            "https://www.linkedin.com/jobs/search/", wait_until="domcontentloaded"
        )

    @pytest.mark.asyncio
    async def test_recommended_jobs_mode_ignores_position_search(self, customizer, mock_page):
        with (
            patch(f"{MODULE}.LINKEDIN_RECOMMENDED_JOBS_MODE", True),
            patch(f"{MODULE}.LINKEDIN_TOP_APPLICANT_JOBS_MODE", False),
            patch(f"{MODULE}.async_pause", new_callable=AsyncMock),
            patch.object(
                customizer, "_set_basic_search_terms", new_callable=AsyncMock
            ) as mock_basic,
            patch.object(customizer, "_commit_basic_search", new_callable=AsyncMock) as mock_commit,
            patch.object(customizer, "_open_all_filters", new_callable=AsyncMock) as mock_filters,
        ):
            await customizer.set_search_params()

        mock_page.goto.assert_called_once_with(
            "https://www.linkedin.com/jobs/collections/recommended/",
            wait_until="domcontentloaded",
        )
        mock_basic.assert_not_called()
        mock_commit.assert_not_called()
        mock_filters.assert_not_called()

    @pytest.mark.asyncio
    async def test_top_applicant_jobs_mode_ignores_position_search(self, customizer, mock_page):
        with (
            patch(f"{MODULE}.LINKEDIN_RECOMMENDED_JOBS_MODE", False),
            patch(f"{MODULE}.LINKEDIN_TOP_APPLICANT_JOBS_MODE", True),
            patch(f"{MODULE}.async_pause", new_callable=AsyncMock),
            patch.object(
                customizer, "_set_basic_search_terms", new_callable=AsyncMock
            ) as mock_basic,
            patch.object(customizer, "_commit_basic_search", new_callable=AsyncMock) as mock_commit,
            patch.object(customizer, "_open_all_filters", new_callable=AsyncMock) as mock_filters,
        ):
            await customizer.set_search_params()

        mock_page.goto.assert_called_once_with(
            "https://www.linkedin.com/jobs/collections/top-applicant/",
            wait_until="domcontentloaded",
        )
        mock_basic.assert_not_called()
        mock_commit.assert_not_called()
        mock_filters.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_all_filter_setters_when_filters_open(self, customizer):
        with (
            patch(f"{MODULE}.LINKEDIN_RECOMMENDED_JOBS_MODE", False),
            patch(f"{MODULE}.LINKEDIN_TOP_APPLICANT_JOBS_MODE", False),
            patch(f"{MODULE}.async_pause"),
            patch.object(customizer, "_set_basic_search_terms", new_callable=AsyncMock),
            patch.object(customizer, "_commit_basic_search", new_callable=AsyncMock),
            patch.object(
                customizer, "_open_all_filters", new_callable=AsyncMock, return_value=True
            ),
            patch.object(
                customizer, "_set_date_posted_filter", new_callable=AsyncMock
            ) as mock_date,
            patch.object(
                customizer, "_set_experience_level_filter", new_callable=AsyncMock
            ) as mock_exp,
            patch.object(
                customizer, "_set_job_type_filter", new_callable=AsyncMock
            ) as mock_job_type,
            patch.object(
                customizer, "_set_work_location_filter", new_callable=AsyncMock
            ) as mock_loc,
            patch.object(customizer, "_set_easy_apply_filter", new_callable=AsyncMock) as mock_easy,
            patch.object(customizer, "_apply_filters", new_callable=AsyncMock, return_value=True),
        ):
            await customizer.set_search_params()

        mock_date.assert_called_once()
        mock_exp.assert_called_once()
        mock_job_type.assert_called_once()
        mock_loc.assert_called_once()
        mock_easy.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_filter_setters_when_filters_not_open(self, customizer):
        with (
            patch(f"{MODULE}.LINKEDIN_RECOMMENDED_JOBS_MODE", False),
            patch(f"{MODULE}.LINKEDIN_TOP_APPLICANT_JOBS_MODE", False),
            patch(f"{MODULE}.async_pause"),
            patch.object(customizer, "_set_basic_search_terms", new_callable=AsyncMock),
            patch.object(customizer, "_commit_basic_search", new_callable=AsyncMock),
            patch.object(
                customizer, "_open_all_filters", new_callable=AsyncMock, return_value=False
            ),
            patch.object(
                customizer, "_set_date_posted_filter", new_callable=AsyncMock
            ) as mock_date,
        ):
            await customizer.set_search_params()

        mock_date.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_on_page_navigation_error(self, customizer, mock_page):
        mock_page.goto.side_effect = Exception("network error")
        with (
            patch(f"{MODULE}.LINKEDIN_RECOMMENDED_JOBS_MODE", False),
            patch(f"{MODULE}.LINKEDIN_TOP_APPLICANT_JOBS_MODE", False),
            patch(f"{MODULE}.async_pause"),
        ):
            with pytest.raises(Exception, match="network error"):
                await customizer.set_search_params()
