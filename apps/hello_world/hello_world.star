"""
Applet: Hello World
Summary: Starter Tidbyt app
Description: Greets someone by name. Set ?who=Name in the pixlet serve URL to change it.
"""

load("render.star", "render")

DEFAULT_WHO = "World"

def main(config):
    # Always fall back to a default so the app renders without config.
    who = config.get("who", DEFAULT_WHO)

    return render.Root(
        child = render.Box(
            # Box fills the 64x32 screen and centers its child
            child = render.Column(
                cross_align = "center",
                children = [
                    render.Text("Hello,", color = "#7fdbff"),
                    render.Text(who + "!", font = "6x13", color = "#ffdc00"),
                ],
            ),
        ),
    )
