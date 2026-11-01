import { Link } from "react-router-dom";
import { EmptyState, PageHeader, Panel } from "../components";

export default function NotFoundPage() {
  return (
    <>
      <PageHeader title="Page not found" />
      <Panel>
        <EmptyState
          title="There is no page at this address"
          action={
            <Link to="/" className="btn btn-secondary btn-sm">
              Back to the live board
            </Link>
          }
        />
      </Panel>
    </>
  );
}
