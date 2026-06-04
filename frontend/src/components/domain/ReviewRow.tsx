import { Star } from "lucide-react";
import { Link } from "react-router-dom";
import type { ReviewDto } from "@/api/types";
import { parseRatingValue, relativeTime } from "@/lib/format";
import { cn } from "@/lib/cn";
import { staggerDelay } from "@/lib/animate";
import { normalizeUsernameRef, userProfilePath } from "@/lib/usernames";

interface Props {
  review: ReviewDto;
  index?: number;
}

export function ReviewRow({ review: rawReview, index = 0 }: Props) {
  const review = {
    ...rawReview,
    author_username: normalizeUsernameRef(rawReview.author_username),
  };
  const rating = parseRatingValue(review.rating);
  const stars = rating === null ? 0 : Math.max(0, Math.min(5, Math.round(rating)));
  const authorUsername = normalizeUsernameRef(review.author_username);
  const authorPath = userProfilePath(authorUsername);
  const authorLabel = authorUsername
    ? `от @${review.author_username}`
    : "автор недоступен";
  return (
    <div
      className="bg-panel border border-border rounded-card p-3 animate-fadein"
      style={staggerDelay(index, 25, 200)}
    >
      <div className="flex items-center gap-2 text-sm">
        <div className="flex items-center gap-0.5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Star
              key={i}
              className={cn("size-4", i < stars ? "text-accent" : "text-text-muted/30")}
              fill={i < stars ? "currentColor" : "none"}
              strokeWidth={1.5}
            />
          ))}
        </div>
        {authorPath ? (
          <Link to={authorPath} className="text-text-muted hover:text-text">
            {authorLabel}
          </Link>
        ) : (
          <span className="text-text-muted">{authorLabel}</span>
        )}
        {review.deal_id != null && (
          <Link
            to={`/deals/${review.deal_id}`}
            className="text-text-muted/80 px-1.5 py-0.5 rounded-full bg-panel-2 text-[10px]"
          >
            сделка #{review.deal_id}
          </Link>
        )}
        <span className="text-text-muted ml-auto text-xs">{relativeTime(review.created_at)}</span>
      </div>
      {review.text && <div className="mt-2 text-sm whitespace-pre-wrap break-words">{review.text}</div>}
    </div>
  );
}
