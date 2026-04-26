/**
 * Cloudinary React starter-kit style delivery: same public_id with
 * improve · sharpen · q_auto · f_auto (matches backend philosophy).
 */
import { useMemo } from 'react'
import { AdvancedImage } from '@cloudinary/react'
import { Cloudinary } from '@cloudinary/url-gen'
import { improve, sharpen } from '@cloudinary/url-gen/actions/adjust'
import { format, quality } from '@cloudinary/url-gen/actions/delivery'
import { scale } from '@cloudinary/url-gen/actions/resize'
import { auto as qAuto } from '@cloudinary/url-gen/qualifiers/quality'
import { auto as fAuto } from '@cloudinary/url-gen/qualifiers/format'

type Props = {
  cloudName: string
  publicId: string
  /** Max width for layout */
  maxWidth?: number
  alt: string
  className?: string
}

export function CldEnhancedImage({ cloudName, publicId, maxWidth = 880, alt, className }: Props) {
  const img = useMemo(() => {
    const cld = new Cloudinary({ cloud: { cloudName }, url: { secure: true } })
    return cld
      .image(publicId)
      .resize(scale().width(maxWidth))
      .adjust(improve())
      .adjust(sharpen(80))
      .delivery(quality(qAuto()))
      .delivery(format(fAuto()))
  }, [cloudName, publicId, maxWidth])

  return <AdvancedImage cldImg={img} alt={alt} className={className} />
}
