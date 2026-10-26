import { useEffect, useState } from "react";
import { Editor } from "./Editor";
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
  const id = useHash().match(/^#\/a\/([0-9a-f]{12})$/)?.[1];
  return id ? <Editor key={id} id={id} /> : <Library />;
}
