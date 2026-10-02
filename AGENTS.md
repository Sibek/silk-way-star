# Calendar updates

Update the SWHL source schedule only when the user requests an update in chat.
Do not install or enable scheduled source fetching on GitHub, Mac, Raspberry Pi, or Codex automations.
When asked to update games, fetch the current source, preserve stable match UIDs,
keep the agreed formatting and alarms, publish through the existing GitHub Pages
workflow, and verify the public ICS. Subscribers keep the same URL.
GitHub Actions may automatically publish committed changes; this is deployment,
not automatic polling of the SWHL schedule.
