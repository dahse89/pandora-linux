-- Pandora Linux; Hyprland 0.56.2 Lua, independent of HOST dotfiles.
hl.monitor({ output = "", mode = "preferred", position = "auto", scale = "auto" })
hl.config({
    input = { kb_layout = "de" },
    general = { gaps_in = 5, gaps_out = 10, border_size = 2, layout = "dwindle" },
    decoration = { rounding = 6 },
})
hl.env("TERMINAL", "ghostty")
hl.env("DMS_DEFAULT_LAUNCH_PREFIX", "uwsm app --")

-- Only the compositor starts DMS. No globally enabled dms.service.
-- A separate UWSM app service follows graphical-session.target on logout.
hl.on("hyprland.start", function()
    hl.exec_cmd("uwsm finalize TERMINAL DMS_DEFAULT_LAUNCH_PREFIX && uwsm app -s b -t service -- dms run")
end)

hl.bind("SUPER + RETURN", hl.dsp.exec_cmd("uwsm app -- ghostty"))
hl.bind("SUPER + Q", hl.dsp.window.close())
hl.bind("SUPER + SPACE", hl.dsp.exec_cmd("dms ipc call spotlight toggle"))
hl.bind("SUPER + SHIFT + S", hl.dsp.exec_cmd("uwsm app -- pandora-screenshot"))
-- Open DMS's confirmation menu instead of killing the compositor.
hl.bind("SUPER + SHIFT + E", hl.dsp.exec_cmd("dms ipc call powermenu toggle"))
hl.bind("SUPER + V", hl.dsp.window.float({ action = "toggle" }))
for _, direction in ipairs({ "left", "right", "up", "down" }) do
    hl.bind("SUPER + " .. direction, hl.dsp.focus({ direction = direction }))
end
for i = 1, 10 do
    local key = i % 10
    hl.bind("SUPER + " .. key, hl.dsp.focus({ workspace = i }))
    hl.bind("SUPER + SHIFT + " .. key, hl.dsp.window.move({ workspace = i }))
end
hl.bind("SUPER + mouse:272", hl.dsp.window.drag(), { mouse = true })
hl.bind("SUPER + mouse:273", hl.dsp.window.resize(), { mouse = true })
hl.bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"), { repeating = true })
hl.bind("XF86AudioLowerVolume", hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"), { repeating = true })
hl.bind("XF86AudioMute", hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"))
