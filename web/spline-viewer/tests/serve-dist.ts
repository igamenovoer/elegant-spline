// Serve only the static build so browser tests exercise the shipped assets.
import { resolve } from "node:path";

const directory = resolve("dist");
const files = new Map<string, string>();
for (const path of new Bun.Glob("**/*").scanSync({ cwd: directory, onlyFiles: true })) {
  files.set("/" + path, resolve(directory, path));
}
files.set("/", resolve(directory, "index.html"));

Bun.serve({
  hostname: "127.0.0.1",
  port: 4187,
  fetch(request) {
    const file = files.get(new URL(request.url).pathname);
    return file ? new Response(Bun.file(file)) : new Response(null, { status: 404 });
  },
});
