"""Backup, restore and face-image upload: they handle files from outside, so the attacks are tested too."""
import io
import json
import os
import zipfile

from _util import T, finish, ok, sandbox
from PIL import Image

root = sandbox()
outside = os.path.join(os.path.dirname(root), "tm-outside-%d" % os.getpid())
os.makedirs(outside, exist_ok=True)


def png(size=(240, 90), color=(255, 0, 0, 255), fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, fmt)
    return buf.getvalue()


def gif(frames=3, size=(40, 20)):
    buf = io.BytesIO()
    imgs = [Image.new("RGB", size, (i * 80, 0, 0)) for i in range(frames)]
    imgs[0].save(buf, "GIF", save_all=True, append_images=imgs[1:], duration=100, loop=0)
    return buf.getvalue()


def make_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def theme_json(**extra):
    return json.dumps(dict({"bg": "#000000", "fg": "#ffffff", "accent": "#ffffff", "web": "#ffffff"}, **extra))


def files_under(path):
    return sorted(os.path.relpath(os.path.join(d, f), path) for d, _, fs in os.walk(path) for f in fs)


# ---------------------------------------------------------------- making a backup
T.write_json(os.path.join(root, "mine.json"), json.loads(theme_json(effects=["scanlines"])))
T.write_json(os.path.join(root, "my other.json"), json.loads(theme_json()))
for state in ("active.json", "touch.json", "display.json", "force_mood.json"):
    open(os.path.join(root, state), "w").write("{}")
open(os.path.join(root, "README.md"), "w").write("guide")
os.makedirs(os.path.join(T.FACES_DIR, "mypack"))
open(os.path.join(T.FACES_DIR, "mypack", "happy.png"), "wb").write(png())
open(os.path.join(T.FACES_DIR, "mypack", "awake.gif"), "wb").write(gif())
open(os.path.join(T.FACES_DIR, "mypack", "notes.txt"), "w").write("not a face")
backup = T.make_backup()
names = sorted(zipfile.ZipFile(io.BytesIO(backup)).namelist())
ok("the backup holds the user's themes and face images", names == ["faces/mypack/awake.gif", "faces/mypack/happy.png",
   "themes/mine.json", "themes/my other.json"], names)
ok("...and none of the state files, the guide or stray files", not any(x in " ".join(names) for x in ("active", "touch", "display", "force", "README", "notes")))

# ---------------------------------------------------------------- restoring it somewhere else
second = sandbox()
report = T.restore_backup(backup)
ok("a backup restores into an empty folder", sorted(report["added"]) == names and not report["invalid"] and not report["skipped"], report)
ok("the themes are the same", json.load(open(os.path.join(second, "mine.json")))["effects"] == [{"type": "scanlines"}])
ok("the faces are back", files_under(T.FACES_DIR) == ["mypack/awake.gif", "mypack/happy.png"], files_under(T.FACES_DIR))
report = T.restore_backup(backup)
ok("restoring again skips what is there", not report["added"] and len(report["skipped"]) == 4, report)
T.write_json(os.path.join(second, "mine.json"), json.loads(theme_json(fps=3)))
report = T.restore_backup(backup, overwrite=True)
ok("...unless overwrite is asked for", "themes/mine.json" in report["added"] and "effects" in json.load(open(os.path.join(second, "mine.json"))))
ok("no temporary files are left behind", not [f for f in files_under(second) if f.endswith(".tmp")])

# ---------------------------------------------------------------- hostile zips
third = sandbox()
evil = make_zip({
    "../evil.json": theme_json(),
    "themes/../../evil2.json": theme_json(),
    "/etc/evil3.json": theme_json(),
    "themes/../evil4.json": theme_json(),
    "themes/sub/x.json": theme_json(),
    "themes/.hidden.json": theme_json(),
    "themes\\back.json": theme_json(),
    "faces/../../evil5/happy.png": png(),
    "faces/pack/../../evil6/happy.png": png(),
    "faces/pack/happy.png/../../x.png": png(),
    "faces/a b/happy.png": png(),
    "faces/pack/notamood.png": png(),
    "faces/pack/happy.exe": b"MZ",
    "random.txt": "hi",
})
report = T.restore_backup(evil)
ok("no entry of a hostile zip is accepted", not report["added"], report)
ok("...each one is reported", len(report["invalid"]) == 14, len(report["invalid"]))
ok("nothing was written anywhere", files_under(third) == [] or all(f.startswith("faces") for f in files_under(third)), files_under(third))
ok("nothing outside the folder either", files_under(outside) == [] and not os.path.exists(os.path.join(os.path.dirname(third), "evil.json"))
   and not os.path.exists("/etc/evil3.json"))
report = T.restore_backup(make_zip({"themes/default.json": theme_json(), "themes/matrix.json": theme_json()}))
ok("a file named like a built-in theme is skipped", len(report["skipped"]) == 2 and not report["added"], report)
report = T.restore_backup(make_zip({"themes/broken.json": "{oops", "themes/wrong.json": json.dumps({"bg": "red"}),
                                    "themes/list.json": "[1,2]", "themes/binary.json": b"\xff\xfe\x00"}))
ok("themes that are not valid are reported, not saved", len(report["invalid"]) == 4 and not report["added"] and not os.path.exists(os.path.join(third, "broken.json")), report)
report = T.restore_backup(make_zip({"faces/p/happy.png": b"this is not an image", "faces/p/sad.png": png(size=(3000, 3000))}))
ok("faces that are not real images, or too large, are reported", len(report["invalid"]) == 2 and not report["added"], report)


def raises(fn, *args):
    try:
        fn(*args)
    except ValueError as e:
        return str(e)
    return None


ok("something that is not a zip is refused", raises(T.restore_backup, b"PK nonsense"))
ok("too many files is refused", raises(T.restore_backup, make_zip({"themes/t%d.json" % i: theme_json() for i in range(T.BACKUP_MAX_ENTRIES + 5)})))
ok("a huge upload is refused before it is opened", raises(T.restore_backup, b"x" * (T.BACKUP_MAX_BYTES + 1)))
bomb = make_zip({"themes/bomb.json": "0" * (25 * 1024 * 1024)})
ok("a zip that expands to a huge size is refused", raises(T.restore_backup, bomb), len(bomb))
big_theme = make_zip({"themes/huge.json": " " * (T.THEME_MAX_BYTES + 10)})
ok("a single oversized theme file is rejected without being read", T.restore_backup(big_theme)["invalid"] == ["themes/huge.json (too large)"])
big_face = make_zip({"faces/p/happy.png": b"0" * (T.FACE_MAX_BYTES + 10)})
ok("...and so is an oversized face file", T.restore_backup(big_face)["invalid"] == ["faces/p/happy.png (too large)"])
ok("an empty zip is fine and adds nothing", T.restore_backup(make_zip({})) == {"added": [], "skipped": [], "invalid": []})
report = T.restore_backup(make_zip({"themes/spaced name.json": theme_json()}))
ok("names with spaces are allowed", report["added"] == ["themes/spaced name.json"])

# ---------------------------------------------------------------- uploading faces
fourth = sandbox()
ok("a png is stored under the mood's name", T.store_face("blobs", "happy.png", png()) == "added" and os.path.isfile(os.path.join(T.FACES_DIR, "blobs", "happy.png")))
ok("uploading it again replaces it", T.store_face("blobs", "HAPPY.PNG", png(color=(0, 255, 0, 255))) == "replaced")
ok("...unless replacing is not wanted", T.store_face("blobs", "happy.png", png(), overwrite=False) == "skipped")
ok("'default' is allowed as a name", T.store_face("blobs", "default.png", png()) == "added")
ok("a jpg is converted to a png", T.store_face("blobs", "sad.jpg", png(fmt="JPEG") if False else (lambda b: (Image.new("RGB", (60, 30), (9, 9, 200)).save(b, "JPEG"), b.getvalue())[1])(io.BytesIO())) == "added"
   and Image.open(os.path.join(T.FACES_DIR, "blobs", "sad.png")).mode == "RGBA")
ok("an animated gif is kept as a gif", T.store_face("blobs", "awake.gif", gif()) == "added" and os.path.isfile(os.path.join(T.FACES_DIR, "blobs", "awake.gif")))
ok("its frames survive", Image.open(os.path.join(T.FACES_DIR, "blobs", "awake.gif")).n_frames == 3)
ok("a png for a mood replaces its gif (so the gif does not win)", T.store_face("blobs", "awake.png", png()) == "replaced"
   and not os.path.exists(os.path.join(T.FACES_DIR, "blobs", "awake.gif")) and os.path.exists(os.path.join(T.FACES_DIR, "blobs", "awake.png")))
ok("a single-frame gif becomes a png", T.store_face("blobs", "bored.gif", gif(frames=1)) == "added" and os.path.exists(os.path.join(T.FACES_DIR, "blobs", "bored.png")))
T.store_face("blobs", "cool.png", png(size=(800, 500)))
ok("an oversized image (up to twice the screen) is scaled down", max(Image.open(os.path.join(T.FACES_DIR, "blobs", "cool.png")).size) <= 480)
ok("the drawing keeps its proportions", Image.open(os.path.join(T.FACES_DIR, "blobs", "cool.png")).size == (480, 300))
for pack, name, data, why in [("blobs", "notamood.png", png(), "not a mood"), ("blobs", "handshake.png", png(), "handshake has no face"),
                              ("blobs", "happy.txt", png(), "wrong type"), ("blobs", "happy.png", b"garbage", "not an image"),
                              ("blobs", "happy.png", b"x" * (T.FACE_MAX_BYTES + 1), "too many bytes"), ("blobs", "happy.png", png(size=(2000, 2000)), "too many pixels"),
                              ("../x", "happy.png", png(), "path in the pack name"), ("a/b", "happy.png", png(), "slash in the pack name"),
                              ("", "happy.png", png(), "empty pack name"), ("x" * 40, "happy.png", png(), "long pack name"),
                              ("blobs", "big.gif", gif(frames=61), "too many frames")]:
    ok("refused: %s" % why, raises(T.store_face, pack, name, data) is not None)
ok("an animated gif larger than the screen is refused", raises(T.store_face, "blobs", "awake.gif", gif(size=(600, 400))))
T.store_face("blobs", "../../../evil/happy.png", png())
ok("a path in the file name is ignored (only the name counts)", os.path.isfile(os.path.join(T.FACES_DIR, "blobs", "happy.png"))
   and not os.path.exists(os.path.join(os.path.dirname(fourth), "evil")))
ok("no temporary files are left over", not [f for f in files_under(T.FACES_DIR) if f.endswith(".tmp")])
ok("the pack shows up in the list with its moods", "blobs" in T.list_packs() and "happy" in T.list_packs()["blobs"])

# ---------------------------------------------------------------- deleting a pack
ok("a pack can be deleted", T.delete_pack("blobs") is True and not os.path.exists(os.path.join(T.FACES_DIR, "blobs")))
ok("deleting a missing pack says no", T.delete_pack("blobs") is False)
for bad in ("../", "..", "a/b", "", "x" * 40):
    ok("refused pack name %r" % bad, raises(T.delete_pack, bad) is not None)
target = os.path.join(outside, "precious")
os.makedirs(target)
open(os.path.join(target, "keep.txt"), "w").write("keep")
os.symlink(target, os.path.join(T.FACES_DIR, "linked"))
ok("a symlinked pack is not followed", T.delete_pack("linked") is False and os.path.exists(os.path.join(target, "keep.txt")))

finish()
