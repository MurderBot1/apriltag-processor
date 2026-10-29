//! Client API for the AprilTag camera USB CDC protocol (docs/protocol.md).
pub mod camera;
pub mod clock;
pub mod protocol;
pub mod transport;

pub use camera::{Calibration, Camera, Config, Error, PoseStream, RawTag, TagDef, TagsRaw};
pub use clock::ClockSync;
pub use protocol::{FrameDecoder, Pose, Status, TimeInfo};
pub use transport::{LoopbackTransport, Transport};
