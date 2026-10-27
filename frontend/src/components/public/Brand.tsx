import { GitBranch } from "lucide-react";
import { Link } from "react-router-dom";

export default function Brand() {
  return (
    <Link to="/" className="public-brand" aria-label="DevOps home">
      <span className="public-brand-mark">
        <GitBranch size={22} strokeWidth={1.8} />
      </span>
      <span>
        DevOps<span className="public-brand-dot">.</span>
      </span>
    </Link>
  );
}
