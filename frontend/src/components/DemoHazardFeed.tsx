type Props = {
  hazardLabel: string
}

/**
 * Static “camera” stage matching the design mockup when no live image is available.
 */
export function DemoHazardFeed({ hazardLabel }: Props) {
  return (
    <div className="hp-demo-feed" aria-hidden>
      <div className="hp-demo-feed-vignette" />
      <div className="hp-demo-crop">
        <span className="hp-demo-bracket hp-demo-bracket--tl" />
        <span className="hp-demo-bracket hp-demo-bracket--tr" />
        <span className="hp-demo-bracket hp-demo-bracket--bl" />
        <span className="hp-demo-bracket hp-demo-bracket--br" />
        <div className="hp-demo-crop-inner">
          <span className="hp-demo-crop-caption">Enhanced Camera Feed</span>
        </div>
      </div>
      <div className="hp-demo-hazard-pill" role="presentation">
        <span className="hp-demo-hazard-warn">⚠</span>
        {hazardLabel}
      </div>
    </div>
  )
}
