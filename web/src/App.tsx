import { useEffect, useState } from "react";
import { Editor } from "./Editor";
import { Landing } from "./Landing";
import { landingSeen, markLandingSeen, pickView } from "./landing";
import { Library } from "./Library";

function useHash() {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const on = () => setHash(location.hash);
    addEventListener("hashchange", on);
    return () => removeEventListener("hashchange", on);
  }, []);
  return hash;
}

export default function App() {
  const hash = useHash();
  const [seen, setSeen] = useState(() => landingSeen());
  const view = pickView(hash, seen);
  if (view.name === "editor") return <Editor key={view.id} id={view.id} />;
  if (view.name === "landing") {
    return <Landing onStart={() => { markLandingSeen(); setSeen(true); location.hash = "#/"; }} />;
  }
  return <Library />;
}
