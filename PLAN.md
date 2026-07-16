# Responsive Compact Layout Plan

## Branch

1. Verify the worktree is clean.
2. Create the feature branch:

   ```sh
   git switch -c feature/responsive-compact-layout
   ```

## Layout Changes

1. Add a dedicated usage summary below the tabs showing the credits used, total budget, and percentage used. This is the highest-priority metric and must remain visible at every terminal size.
2. Enter compact mode when either terminal dimension is constrained:
   - Width below approximately 80 columns.
   - Height below approximately 30 rows.
   - Recalculate the mode in response to Textual resize events.
3. In compact mode:
   - Hide the credit chart.
   - Place the model table directly below the usage summary.
   - Let the table use all remaining height.
   - Limit table columns to `Model`, `Reqs`, and `% budget`.
   - Shorten tab labels to `Hour`, `Today`, `Week`, and `Month` if needed.
   - Keep refresh and quit bindings available in the footer.
   - Show the last update time only when space permits.
4. In regular mode:
   - Preserve the current chart and complete model table.
   - Keep the new usage summary visible above the chart.
   - Retain token, credit, `% used`, and `% budget` columns.

## Code Changes

1. Update `estimator.py`:
   - Add a `UsageSummary` widget.
   - Track compact state from `events.Resize`.
   - Toggle a compact CSS class on the app or main container.
   - Hide or show the chart based on compact state.
   - Rebuild model table columns only when the mode changes.
   - Update summary content in `refresh_data()`.
   - Keep data fetching and credit calculations unchanged.
2. Refactor `ModelTable`:
   - Use the existing nine-column schema in regular mode.
   - Use model, requests, and budget contribution in compact mode.
   - Preserve sorting by estimated credit cost.
   - Truncate long model names instead of forcing horizontal scrolling.
3. Update `README.md`:
   - Document compact-pane behavior.
   - Explain which information is prioritized and which columns are hidden.

## Testing

1. Add headless Textual tests using `App.run_test(size=...)`.
2. At a normal size such as `160x50`, verify that the summary, chart, and complete table are visible.
3. At a Herdr-like size such as `40x45`, verify that:
   - The usage summary is visible.
   - The chart is hidden.
   - Model, request count, and `% budget` are visible without horizontal scrolling.
4. Resize a running test across the breakpoint and confirm that the layout switches in both directions.
5. Verify empty-data and zero-budget states.
6. Run:

   ```sh
   uv run pytest
   uv run python -m py_compile estimator.py
   ```

## Acceptance Criteria

- Credits used, total budget, and percentage used are always visible.
- A narrow Herdr pane prioritizes the model list, request counts, and budget contribution.
- The graph does not consume space in compact mode.
- Expanding the pane restores the full chart and table.
- Tab switching and automatic or manual refresh continue to work.
