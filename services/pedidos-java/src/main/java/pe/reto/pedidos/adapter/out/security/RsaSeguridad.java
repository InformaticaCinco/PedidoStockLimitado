package pe.reto.pedidos.adapter.out.security;

import pe.reto.pedidos.application.port.out.Seguridad;
import pe.reto.pedidos.config.Settings;
import pe.reto.pedidos.domain.*;
import static pe.reto.pedidos.domain.Model.*;
import com.nimbusds.jose.*;
import com.nimbusds.jose.crypto.*;
import com.nimbusds.jose.jwk.*;
import com.nimbusds.jwt.*;
import org.mindrot.jbcrypt.BCrypt;
import java.nio.file.*;
import java.security.*;
import java.security.interfaces.RSAPrivateKey;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.*;
import java.time.Clock;
import java.util.*;

public final class RsaSeguridad implements Seguridad {
    private final Settings config;
    private final Clock reloj;
    private final RSAPrivateKey privada;
    private final RSAPublicKey publica;
    private final String kid;
    private final SecureRandom random = new SecureRandom();
    public RsaSeguridad(Settings config, Clock reloj) {
        this.config = config; this.reloj = reloj;
        try {
            KeyFactory factory = KeyFactory.getInstance("RSA");
            privada = (RSAPrivateKey) factory.generatePrivate(new PKCS8EncodedKeySpec(pem(config.privateKey())));
            publica = (RSAPublicKey) factory.generatePublic(new X509EncodedKeySpec(pem(config.publicKey())));
            if (!privada.getModulus().equals(publica.getModulus()) || publica.getModulus().bitLength() < 2048) throw new IllegalArgumentException("Par RSA inválido");
            kid = new RSAKey.Builder(publica).build().computeThumbprint().toString();
        } catch (Exception e) { throw new IllegalStateException("No se pudo cargar el par RSA configurado", e); }
    }
    private static byte[] pem(String path) throws java.io.IOException {
        String texto = Files.readString(Path.of(path)).replaceAll("-----[^-]+-----", "").replaceAll("\\s", "");
        return Base64.getDecoder().decode(texto);
    }
    public boolean verificarClave(String clave, String hash) {
        try { return BCrypt.checkpw(clave, hash); } catch (IllegalArgumentException e) { return false; }
    }
    public String firmar(Usuario u) {
        try {
            JWTClaimsSet claims = new JWTClaimsSet.Builder().subject(u.id()).claim("rol", u.rol().name()).issuer(config.issuer()).audience(config.audience()).issueTime(Date.from(reloj.instant())).expirationTime(Date.from(reloj.instant().plusSeconds(config.accessSeconds()))).jwtID(UUID.randomUUID().toString()).build();
            SignedJWT jwt = new SignedJWT(new JWSHeader.Builder(JWSAlgorithm.RS256).type(JOSEObjectType.JWT).keyID(kid).build(), claims);
            jwt.sign(new RSASSASigner(privada)); return jwt.serialize();
        } catch (JOSEException e) { throw new IllegalStateException("No se pudo firmar JWT", e); }
    }
    public Actor validar(String token) {
        try {
            SignedJWT jwt = SignedJWT.parse(token);
            if (!JWSAlgorithm.RS256.equals(jwt.getHeader().getAlgorithm()) || !kid.equals(jwt.getHeader().getKeyID()) || !jwt.verify(new RSASSAVerifier(publica))) throw new IllegalArgumentException();
            JWTClaimsSet c = jwt.getJWTClaimsSet();
            if (!config.issuer().equals(c.getIssuer()) || !c.getAudience().contains(config.audience()) || c.getExpirationTime() == null || !c.getExpirationTime().toInstant().isAfter(reloj.instant()) || c.getSubject() == null || c.getSubject().isBlank() || (c.getNotBeforeTime() != null && c.getNotBeforeTime().toInstant().isAfter(reloj.instant()))) throw new IllegalArgumentException();
            return new Actor(c.getSubject(), Rol.valueOf(c.getStringClaim("rol")));
        } catch (Exception e) { throw new Fallo(401, "Token inválido"); }
    }
    public String nuevoRefresh() { byte[] bytes = new byte[32]; random.nextBytes(bytes); return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes); }
    public Map<String, Object> jwks() { return new JWKSet(new RSAKey.Builder(publica).keyID(kid).algorithm(JWSAlgorithm.RS256).keyUse(KeyUse.SIGNATURE).build()).toJSONObject(); }
}
